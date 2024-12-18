from payments_py import Payments, Environment
from logger.logger import logger
from config.env import NVM_API_KEY, NVM_ENVIRONMENT

def initialize_payments():
    """Initializes the Payments client."""
    logger.info("Initializing Nevermined Payments client...")
    payments = Payments(
        app_id="orchestrator_agent",
        nvm_api_key=NVM_API_KEY,
        version="1.0.0",
        environment=Environment.get_environment(NVM_ENVIRONMENT),
        ai_protocol=True,
    )

    logger.info(f"Connected to Nevermined environment: {NVM_ENVIRONMENT}")
    return payments
