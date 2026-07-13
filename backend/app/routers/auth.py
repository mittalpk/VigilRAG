from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
import jwt
import datetime
from ..config import settings

router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

import logging
logger = logging.getLogger(__name__)

@router.post("/login")
async def login(body: LoginRequest = Body(...)):
    # Diagnostic: Check if we are still using fallback values
    if settings.admin_password.get_secret_value() == "REPLACE_IN_PORTAL":
        logger.warning("Authentication failed: Backend is still using the fallback 'REPLACE_IN_PORTAL' password.")
    
    if body.username != settings.admin_username or body.password != settings.admin_password.get_secret_value():
        logger.warning(f"Login failed for username='{body.username}'")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = jwt.encode({
        "sub": body.username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, settings.secret_key.get_secret_value(), algorithm="HS256")
    return {"token": token}


