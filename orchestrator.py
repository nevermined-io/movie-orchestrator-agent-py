import asyncio
import json
from payments_py.utils import generate_step_id
from payments_py.data_models import AgentExecutionStatus
from payments.ensure_balance import ensure_sufficient_balance
from logger.logger import logger
from utils.log_message import log_message
from config.env import (
    SCRIPT_GENERATOR_DID,
    CHARACTER_EXTRACTOR_DID,
    IMAGE_GENERATOR_DID,
    THIS_PLAN_DID,
    IMAGE_GENERATOR_PLAN_DID,
)

class OrchestratorAgent:
    def __init__(self, payments):
        self.payments = payments

    async def run(self, data):
        """
        Processes incoming steps received from the AI Protocol subscription.
        Steps are routed to their appropriate handlers based on their name.

        Args:
            payments: Payments API instance used for querying and updating steps.
            data: The incoming step data from the subscription.
        """
        logger.info(f"Received event: {data}")
        step = self.payments.ai_protocol.get_step(data["step_id"])

        await log_message(
            self.payments, 
            step["task_id"], 
            "info", 
            f"Processing Step {step['step_id']} [{step['step_status']}]: {step['input_query']}", 
            AgentExecutionStatus.Pending
        )

        # Only process steps with status "Pending"
        if step["step_status"] != "Pending":
            logger.warning(f"{step['task_id']} :: Step {step['step_id']} is not pending. Skipping.")
            return

        # Route step to the appropriate handler
        if step["name"] == "init":
            await self.handle_init_step(step)
        elif step["name"] == "generateScript":
            await self.handle_step_with_agent(step, SCRIPT_GENERATOR_DID, "Script Generator", THIS_PLAN_DID)
        elif step["name"] == "extractCharacters":
            await self.handle_step_with_agent(step, CHARACTER_EXTRACTOR_DID, "Character Extractor", THIS_PLAN_DID)
        elif step["name"] == "generateImagesForCharacters":
            await self.handle_image_generation_for_characters(step)
        else:
            logger.warning(f"Unrecognized step name: {step['name']}. Skipping.")


    async def handle_init_step(self, step):
        """
        Handles the initialization step by creating subsequent steps in the workflow.

        Args:
            step: The current step being processed.
        """
        script_step_id = generate_step_id()
        character_step_id = generate_step_id()
        image_step_id = generate_step_id()

        # Define the steps with their predecessors
        steps = [
            {"step_id": script_step_id, "task_id": step["task_id"], "predecessor": step["step_id"], "name": "generateScript", "is_last": False},
            {"step_id": character_step_id, "task_id": step["task_id"], "predecessor": script_step_id, "name": "extractCharacters", "is_last": False},
            {"step_id": image_step_id, "task_id": step["task_id"], "predecessor": character_step_id, "name": "generateImagesForCharacters", "is_last": True},
        ]

        self.payments.ai_protocol.create_steps(step["did"], step["task_id"], {"steps": steps})
        await log_message(self.payments, step["task_id"], "info", "Steps created successfully.")

        # Mark the init step as completed
        self.payments.ai_protocol.update_step(step["did"], step["task_id"], step_id=step["step_id"], step={"step_status": "Completed", "output": step["input_query"]})


    async def handle_step_with_agent(self, step, agent_did, agent_name, plan_did):
        """
        Handles a step by querying a sub-agent for task execution.

        Args:
            step: The current step being processed.
            agent_did: The DID of the sub-agent responsible for the task.
            agent_name: A friendly name for the sub-agent for logging purposes.
            plan_did: The DID of the plan associated with the agent.
        """
        has_balance = await ensure_sufficient_balance(plan_did, self.payments)
        if not has_balance:
            return

        task_data = {"query": step["input_query"], "name": step["name"], "additional_params": [], "artifacts": []}

        async def task_callback(data):
            task_log = json.loads(data)
            if task_log.get("task_status", None) == "Completed":
                await self.validate_generic_task(task_log["task_id"], agent_did, step)
            else:
                await log_message(self.payments, step["task_id"], "info", task_log['message'])

        result = await self.payments.ai_protocol.create_task(agent_did, task_data, task_callback)
        if getattr(result, "status_code", 0) == 201:
            await log_message(self.payments, step["task_id"], "info", "Task created successfully.")
        else:
            await log_message(
                self.payments, 
                step["task_id"], 
                "error", 
                f"Error creating task for {agent_name}: {result}", 
                AgentExecutionStatus.Failed
            )



    async def handle_image_generation_for_characters(self, step):
        """
        Handles image generation for multiple characters. Ensures all tasks are completed before marking the step as finished.

        Args:
            step: The current step being processed.
        """
        characters = json.loads(step.get("input_artifacts", "[]"))
        tasks = []
        characters_json = json.loads(characters)

        has_balance = await ensure_sufficient_balance(
            IMAGE_GENERATOR_PLAN_DID, self.payments, len(characters_json)
        )
        if not has_balance:
            raise Exception("Insufficient balance for image generation tasks.")
        
        for character in characters_json:
            prompt = self.generate_text_to_image_prompt(character)
            tasks.append(self.query_agent_with_prompt(step, prompt, "Image Generator", self.validate_image_generation_task))

        try:
            artifacts = await asyncio.gather(*tasks, return_exceptions=False)
            await log_message(
                self.payments, 
                step["task_id"], 
                "info", 
                "All image tasks completed.", 
                AgentExecutionStatus.Completed
            )
            self.payments.ai_protocol.update_step(step["did"], step["task_id"], step_id=step["step_id"], step={"step_status": "Completed", "output": "All image tasks completed.", "output_artifacts": artifacts})
        except Exception as e:
            self.payments.ai_protocol.update_step(step["did"], step["task_id"], step_id=step["step_id"], step={"step_status": "Failed", "output": "One or more image tasks failed."})
            await log_message(
                self.payments, 
                step["task_id"], 
                "error", 
                f"Error during image tasks: {str(e)}", 
                AgentExecutionStatus.Failed
            )


    def generate_text_to_image_prompt(self, character):
        """
        Generates a prompt string for a text-to-image model from a character object.

        Args:
            character: A dictionary containing character attributes.
        Returns:
            str: The generated prompt string.
        """
        return ", ".join(value for key, value in character.items() if key != "name")

    async def query_agent_with_prompt(self, step, prompt, agent_name, validate_task_fn):
        """
        Queries an agent with a prompt, validates the task, and resolves with artifacts.

        Args:
            step: The current step being processed.
            prompt: The input prompt for the agent.
            agent_name: The agent's name, for logging purposes.
            validate_task_fn: Function to validate task completion.

        Returns:
            The artifacts produced by the agent's task.
        """
        # Create a Future object to track completion
        task_future = asyncio.get_event_loop().create_future()

        async def task_callback(data):
            """Handles updates from the sub-agent's task."""
            task_log = json.loads(data)
            print('RECIBIENDO EVENTO TASK LOG:::')
            if task_log.get("task_status", None) == AgentExecutionStatus.Completed.value:
                artifacts = await validate_task_fn(task_log["task_id"])
                print("Finished task:", task_log["task_id"], artifacts)
                task_future.set_result(artifacts)  # Mark task as completed with artifacts
            elif task_log.get("task_status", None) == AgentExecutionStatus.Failed.value:
                await log_message(self.payments, step["task_id"], "error", task_log['message'], AgentExecutionStatus.Failed)
                print("Task failed:", task_log["task_id"], task_log)
                task_future.set_exception(Exception("Sub-agent task failed"))
            else:
                print("Task info:", task_log)
                await log_message(self.payments, step["task_id"], "info", task_log['message'])

        # Define task data and create the task
        task_data = {"query": prompt, "name": step["name"], "additional_params": [], "artifacts": []}
        result = await self.payments.ai_protocol.create_task(
            IMAGE_GENERATOR_DID, task_data, task_callback
        )

        if result.status_code != 201:
            raise Exception(f"Error creating task for {agent_name}: {result.data}")

        # Await the Future until task_callback sets the result or exception
        return await task_future

    
    async def validate_generic_task(self, task_id, agent_did, parent_step):
        """
        Validates a generic task's completion and updates the parent step accordingly.

        Args:
            task_id: The ID of the task to validate.
            agent_did: The DID of the agent that executed the task.
            access_config: Access configuration required to query the agent's data.
            parent_step: The parent step that initiated the task.
        """
        task_result = self.payments.ai_protocol.get_task_with_steps(agent_did, task_id)
        task_data = task_result.json()

        status = "Completed" if task_data["task"]["task_status"] == "Completed" else "Failed"
        self.payments.ai_protocol.update_step(
            parent_step["did"], 
            parent_step["task_id"], 
            step_id=parent_step["step_id"], 
            step={
                "step_status": status, 
                "output": task_data["task"].get("output", "Error during task execution"), 
                "output_artifacts": task_data["task"].get("output_artifacts", [])
            }
        )


    async def validate_image_generation_task(self, task_id):
        """
        Validates the completion of an image generation task and retrieves its artifacts.

        Args:
            task_id: The ID of the image generation task.
            access_config: Access configuration required to query the agent's data.

        Returns:
            list: An array of output artifacts generated by the task.
        """
        task_result = self.payments.ai_protocol.get_task_with_steps(IMAGE_GENERATOR_DID, task_id)
        task_json = task_result.json()
        return task_json["task"].get("output_artifacts", [])
