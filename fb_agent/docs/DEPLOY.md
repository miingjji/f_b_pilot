# 배포 (Streamlit Community Cloud)

저장소를 그대로 연결해 상시 URL을 만든다. 실제 매장 데이터(`fb_agent/data/`)가 저장소에 들어 있으므로 **저장소는 비공개로 두고, 앱 접근을 이메일로 제한**한다.

## 준비 상태 (코드)
- 저장소 루트에서 실행돼도 로고·자료를 찾는다: 자료 경로는 `__file__` 기준, 로고는 `config.ASSETS`.
- 루트 `.streamlit/config.toml` 은 `fb_agent/.streamlit/config.toml` 과 같은 내용의 복사본이다 (배포 환경은 루트의 설정만 읽는다). 앱 폴더의 설정을 바꾸면 루트에도 복사한다 — `test_deploy.py` 가 두 파일이 다르면 실패한다.
- 의존 패키지: `fb_agent/requirements.txt` (streamlit, pandas, numpy, altair, openpyxl, xlrd, odfpy). 비밀값(secrets)은 필요 없다.
- 저장소를 새로 받아 루트에서 `streamlit run fb_agent/app.py` 로 띄워 홈과 주요 화면 9개를 열어 확인했다 (예외 없음, 메모리 약 310MB).

## 배포 순서 (share.streamlit.io, 본인 GitHub 계정으로)
1. **Create app → Deploy a public app from GitHub** 를 선택하고 저장소 `miingjji/f_b_pilot` 을 고른다 (비공개 저장소면 GitHub 연결 권한을 허용).
2. Branch `main`, **Main file path `fb_agent/app.py`**.
3. **Advanced settings → Python version 3.12** (3.13도 가능). Secrets 는 비워 둔다.
4. Deploy. 처음에는 패키지 설치로 몇 분 걸린다.
5. 배포 후 앱 **Settings → Sharing** 에서 **Only specific people can view this app** 을 고르고 교수님 이메일을 추가한다 (이 설정 전에는 링크를 아는 누구나 볼 수 있다).

## 알아둘 것
- 로그인은 데모(아이디·비밀번호 비워 두고 입장)라 앱 자체에는 인증이 없다. 접근 제한은 위 Sharing 설정이 전부다.
- 일정 추가·구매청구 같은 입력은 접속(세션)마다 초기화된다 (서버에 저장하지 않는다).
- 한동안 접속이 없으면 앱이 잠들고, 다시 열 때 깨우는 데 시간이 걸린다.
- 코드를 `main` 에 푸시하면 배포가 자동으로 갱신된다.
