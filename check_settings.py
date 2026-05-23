from config.settings import settings
print("=== 현재 설정 확인 ===")
print(f"모드: {settings.TRADE_MODE}")
key_preview = (settings.APP_KEY[:8] + "...") if settings.APP_KEY else "(없음)"
print(f"APP_KEY: {key_preview}")
print(f"APP_SECRET 길이: {len(settings.APP_SECRET)}")
print(f"CANO: {settings.CANO}")
print(f"BASE_URL: {settings.BASE_URL}")
print(f"validate: {settings.validate()}")
print(f"describe: {settings.describe()}")
