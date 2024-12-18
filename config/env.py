import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Nevermined and OpenAI configuration
NVM_API_KEY = os.getenv("NVM_API_KEY")
NVM_ENVIRONMENT = os.getenv("NVM_ENVIRONMENT", "testing")
THIS_PLAN_DID = os.getenv("THIS_PLAN_DID")
IMAGE_GENERATOR_PLAN_DID = os.getenv("IMAGE_GENERATOR_PLAN_DID")
THIS_AGENT_DID = os.getenv("THIS_AGENT_DID")
SCRIPT_GENERATOR_DID = os.getenv("SCRIPT_GENERATOR_DID")
CHARACTER_EXTRACTOR_DID = os.getenv("CHARACTER_EXTRACTOR_DID")
IMAGE_GENERATOR_DID = os.getenv("IMAGE_GENERATOR_DID")
