import asyncio
import json
from payments_py.utils import generate_step_id
from payments_py.data_models import AgentExecutionStatus
from payments.ensure_balance import ensure_sufficient_balance
from logger.logger import logger
from utils.log_message import log_message
from classes.TaskRegistry import TaskRegistry
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
            if data.get("task_status", None) == AgentExecutionStatus.Completed.value:
                await self.validate_generic_task(data["task_id"], agent_did, step)

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
            await self.error_generic_task(step)


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
            task = asyncio.ensure_future(self.query_agent_with_prompt(step, prompt, "Image Generator"))
            tasks.append(task)

        try:
            # Execute all tasks concurrently and wait for their completion
            artifacts = await asyncio.gather(*tasks)
            print(":::HEMOS TERMINADO TODAS LAS TAREAS:::")
            self.payments.ai_protocol.update_step(
                step["did"], 
                step["task_id"], 
                step_id=step["step_id"], 
                step={
                    "step_status": AgentExecutionStatus.Completed, 
                    "output": "All image tasks completed.", 
                    "output_artifacts": artifacts,
                    "is_last": True
                }
            )
        except Exception as e:
            self.payments.ai_protocol.update_step(
                step["did"], 
                step["task_id"], 
                step_id=step["step_id"], 
                step={
                    "step_status": AgentExecutionStatus.Failed, 
                    "output": "One or more image tasks failed.",
                    "output_artifacts": artifacts,
                    "is_last": True
                }
            )

    def generate_text_to_image_prompt(self, character):
        """
        Generates a prompt string for a text-to-image model from a character object.

        Args:
            character: A dictionary containing character attributes.
        Returns:
            str: The generated prompt string.
        """
        text =  ", ".join(value for key, value in character.items() if key != "name")

        return text
    
    async def task_callback(self, data):
        """
        Handles updates from the sub-agent's task.

        Args:
            data: JSON data from the sub-agent.
        """
        task_id = data.get("task_id")

        # Retrieve the Future associated with the task_id
        task_future = await TaskRegistry.get_task(task_id)
        if not task_future:
            print(f"Received task update for unknown task_id: {task_id}")
            return

        try:
            if data.get("task_status", None) == AgentExecutionStatus.Completed.value:
                artifacts = await self.validate_image_generation_task(task_id)
                task_future.set_result(artifacts)
            elif data.get("task_status", None) == AgentExecutionStatus.Failed.value:
                task_future.set_exception(Exception("Sub-agent task failed"))
            else:
                print(f"Task {task_id} is still in progress.")
        except Exception as e:
            task_future.set_exception(e)
        finally:
            # Remove the Future from the TaskRegistry once it is resolved
            await TaskRegistry.remove_task(task_id)



    async def query_agent_with_prompt(self, step, prompt, agent_name):
        """
        Queries an agent with a prompt, validates the task, and resolves with artifacts.

        Args:
            step: The current step being processed.
            prompt: The input prompt for the agent.
            agent_name: The agent's name, for logging purposes.

        Returns:
            The artifacts produced by the agent's task.
        """
        # Create a Future to track the task
        task_future = asyncio.get_event_loop().create_future()

        # Define the task data
        task_data = {"query": prompt, "name": step["name"], "additional_params": [], "artifacts": []}


        # Create the task and retrieve the task_id
        result = await self.payments.ai_protocol.create_task(
            IMAGE_GENERATOR_DID, task_data, self.task_callback
        )

        if result.status_code != 201:
            raise Exception(f"Error creating task for {agent_name}: {result.data}")

        # Parse the task_id from the response
        res_json = result.json()
        task_id = res_json.get("task", {}).get("task_id")
        if not task_id:
            raise Exception("Failed to retrieve task_id from the sub-agent.")

        # Register the Future in the TaskRegistry
        await TaskRegistry.add_task(task_id, task_future)

        # Wait for the Future to be resolved or rejected
        return await task_future

    
    async def validate_generic_task(self, task_id, agent_did, summoner_step):
        """
        Validates a generic task's completion and updates the parent step accordingly.

        Args:
            task_id: The ID of the task to validate.
            agent_did: The DID of the agent that executed the task.
            access_config: Access configuration required to query the agent's data.
            summoner_step: The parent step that initiated the task.
        """
        task_result = self.payments.ai_protocol.get_task_with_steps(agent_did, task_id)
        task_data = task_result.json()

        print(f"::: SOLVING STEP {summoner_step['step_id']} :::")
        self.payments.ai_protocol.update_step(
            summoner_step["did"], 
            summoner_step["task_id"], 
            step_id=summoner_step["step_id"], 
            step={
                "step_status": task_data["task"]["task_status"], 
                "output": task_data["task"].get("output", "Error during task execution"), 
                "output_artifacts": task_data["task"].get("output_artifacts", []),
                "is_last": False
            }
        )

    async def error_generic_task(self, step):
        """
        Updates a step's status to 'Failed' when an error occurs during task execution.

        Args:
            step: The step to update.
        """
        self.payments.ai_protocol.update_step(step["did"], step["task_id"], step_id=step["step_id"], step={"step_status": AgentExecutionStatus.failed.value, "output": "Error during subtask execution."})


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
        return task_json["task"].get("output_artifacts", "")
