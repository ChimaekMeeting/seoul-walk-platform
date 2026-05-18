import secrets

# SECRET_KEY 발급
print(f"ACCESS_SECRET_KEY: {secrets.token_hex(32)}")
print(f"REFRESH_SECRET_KEY: {secrets.token_hex(32)}")