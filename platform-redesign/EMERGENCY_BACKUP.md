# 긴급 코드 보존

2026-10-07 사용자 요청으로 추가 기능 검증 없이 현재 소스를 비공개 GitHub 백업에 저장한다. 구현은 계속 일시중단 상태다.

- 저장소: https://github.com/hurxxxx/miy-emergency-backup-20261007 (private)
- 백업 브랜치: emergency/20261007-server-restart
- 기존 checkout: dev, 기준 HEAD 449d1417afbf6a2eb978c1465c765e26ef43c5dc
- 기존 origin/upstream과 dev 브랜치·작업 파일·기존 index는 그대로 보존한다. 공개 upstream의 DISABLED push 설정은 바꾸지 않는다.
- 백업은 현재 전체 source tree의 별도 root commit이다. 기존 Git history는 포함하지 않으며 기준 HEAD로 원래 history를 식별한다. 테스트 통과·배포 승인·구현 완료를 뜻하지 않는다.
- Git에서 제외된 환경파일·자격증명·runtime 로그·DB·실행 데이터는 GitHub에 보내지 않는다. 로컬 source archive와 snapshot bundle은 .runtime/emergency-backups/에 보관한다.
- 재개 지점은 [RESTART_CHECKPOINT.md](RESTART_CHECKPOINT.md)다.
