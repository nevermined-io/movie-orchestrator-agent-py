from logger.logger import logger

async def ensure_sufficient_balance(plan_did, payments, required_balance=1):
    """Ensures the plan has sufficient balance and orders credits if necessary."""
    logger.info(f"Checking balance for plan {plan_did}...")
    balance = payments.get_plan_balance(plan_did)

    if int(balance.balance) < required_balance:
        logger.info(f"Balance insufficient for plan {plan_did}. Required: {required_balance}, Available: {balance.balance}. Ordering credits...")
        response = payments.order_plan(plan_did)
        if not response.success:
            logger.error(f"Failed to order credits for plan {plan_did}.")
            return False
    return True
