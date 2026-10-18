"""Map provider errors to useful messages without disclosing credentials or raw payloads."""
from openai import AuthenticationError, RateLimitError, APIConnectionError, APITimeoutError

def public_error(error):
    if isinstance(error,AuthenticationError):
        return 'OpenAI rejected the API key. Update backend/.env and restart the backend.'
    if isinstance(error,RateLimitError):
        body=getattr(error,'body',{}) or {}
        code=body.get('code') or body.get('error',{}).get('code') if isinstance(body,dict) else None
        if code in ('insufficient_quota','credit_balance_exhausted') or 'no credits remaining' in str(error).lower():
            return 'OpenAI API credits are exhausted. Add credits or use a funded project key, restart if the key changed, and retry. The existing knowledge base is unchanged.'
        return 'OpenAI rate limit reached. Wait briefly and retry.'
    if isinstance(error,(APIConnectionError,APITimeoutError)):
        return 'Could not reach OpenAI. Check the network connection and retry.'
    return 'Operation failed. Check backend logs and OpenAI configuration, then retry.'
