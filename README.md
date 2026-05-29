# Discord Minecraft Whitelist Bot

Discord 사용자가 봇에게 1대1 DM으로 Minecraft 닉네임만 보내면 Paper 서버 whitelist에 자동 등록되는 Python 봇입니다. 서버 채널에서는 기존처럼 `/verify 닉네임`도 사용할 수 있습니다.

## 주요 기능

- DM 인증: 사용자가 봇에게 `Steve` 또는 `/verify Steve` 전송
- 서버 채널 인증: `/verify username`
- Minecraft Java 닉네임 검증: `^[A-Za-z0-9_]{3,16}$`
- Discord 계정 1개당 Minecraft 닉네임 2개 제한
- SQLite DB로 등록 기록 저장
- RCON으로 `whitelist add/remove` 실행
- 선택 기능: 운영진 승인 버튼, 인증 완료 역할 부여, 화이트리스트 로그 채널 알림
- 관리자 명령: `/whitelist-add`, `/whitelist-remove`, `/whitelist-check`, `/whitelist-list`
- 서버 주소 조회: `/server-address`

## 빠른 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
python bot.py
```

Windows 개발 환경:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python bot.py
```

## DM 인증 설정

`.env`에서 기본값은 DM 인증 허용입니다.

```env
ALLOW_DM_VERIFY=true
```

Discord Developer Portal의 Bot 설정에서 DM 텍스트 입력을 읽기 위해 `Message Content Intent`를 켜세요. 사용자는 봇 프로필을 열고 메시지 보내기에서 닉네임만 보내면 됩니다.

```text
Steve
```

또는:

```text
/verify Steve
```

## Minecraft server.properties

```properties
online-mode=true
white-list=true
enforce-whitelist=true
enable-rcon=true
rcon.port=25575
rcon.password=강력한_RCON_비밀번호
```

RCON 포트 `25575`는 Google Cloud 방화벽에서 외부 공개하지 마세요. 봇을 같은 VM에서 실행하고 `RCON_HOST=127.0.0.1`로 쓰는 구성이 안전합니다.

RCON 응답이 느린 서버라면 대기 시간을 늘릴 수 있습니다.

```env
RCON_TIMEOUT_SECONDS=60
```

화이트리스트 추가 성공 로그를 Discord 채널에 남기려면:

```env
WHITELIST_LOG_CHANNEL_ID=1508093161329660116
```

## Discord 권한

OAuth2 Scope:

```text
bot
applications.commands
```

최소 권한:

```text
View Channels
Send Messages
Read Message History
Use Slash Commands
```

DM 닉네임 입력을 쓰려면 Bot 설정에서 다음 Intent를 켭니다.

```text
Message Content Intent
```

인증 역할 자동 부여를 쓰려면 `Manage Roles` 권한과 `VERIFIED_ROLE_ID`가 필요합니다.
