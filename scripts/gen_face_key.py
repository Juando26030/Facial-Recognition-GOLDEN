"""Genera una llave nueva para cifrar el dato biométrico. Se imprime UNA vez: cópiala al `.env` de la VM como FACE_ENCRYPTION_KEY=... y guárdala también en un
gestor de contraseñas. PERDER LA LLAVE = PERDER los rostros cifrados. No la pegues en chats ni documentos.

    python scripts/gen_face_key.py
"""
from cryptography.fernet import Fernet

print(Fernet.generate_key().decode())
