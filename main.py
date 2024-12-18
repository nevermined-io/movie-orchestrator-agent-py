import asyncio
from payments.payments_instance import initialize_payments
from orchestrator import OrchestratorAgent
from config.env import THIS_AGENT_DID

async def main():
    """Main entry point for the orchestrator agent."""
    payments = initialize_payments()
    agent = OrchestratorAgent(payments)

    # Subscribe to the ai_protocol with the agent's `run` method
    subscription_task = asyncio.get_event_loop().create_task(
        payments.ai_protocol.subscribe(
            agent.run, 
            join_account_room=False, 
            join_agent_rooms=[THIS_AGENT_DID], 
            get_pending_events_on_subscribe=False
        )
    )
    try:
        await subscription_task
    except asyncio.CancelledError:
        print("Subscription task was cancelled")

if __name__ == "__main__":
    asyncio.run(main())
