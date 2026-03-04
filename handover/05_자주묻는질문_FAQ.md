# 자주 묻는 질문 (FAQ)

## Q1. app.py가 6,000줄이 넘는데 왜 파일을 안 나눴나요?

Streamlit 앱 특성상 단일 파일이 관리하기 편합니다. 프로세서와 HTML 생성기는 이미 분리되어 있고,
app.py에는 UI 로직 + 비즈니스 정책(상품 사전)이 섞여 있습니다.
향후 리팩토링 시 `정책 사전(POLICY dicts)`을 별도 파일로 분리하면 좋습니다.

## Q2. 함수가 왜 여러 번 정의되어 있나요?

빠른 기능 추가를 위해 기존 함수를 유지하면서 아래에 새 버전을 정의하는 방식으로 개발했습니다.
Python에서는 마지막 정의가 유효합니다. **항상 맨 아래(마지막) 정의를 수정하세요.**

특정 함수의 모든 정의 위치를 찾으려면:
```bash
grep -n "^def render_action_plan_editor" app.py
```

## Q3. 새 엑셀 형식이 추가되면?

1. `src/utils.py`의 `FILE_PATTERNS`에 새 정규식 패턴 추가
2. 해당 프로세서(`src/processors/`)에서 새 컬럼명 처리 로직 추가
3. 기존 하위 호환 패턴은 삭제하지 않고 유지 (이전 파일도 지원)

## Q4. 보고서에 새 섹션을 추가하려면?

1. **데이터 준비**: `src/reporting/html_generator.py`의 `prepare_XXX_data()` 함수 추가/수정
2. **템플릿 수정**: 같은 파일의 Jinja2 HTML 부분에 섹션 추가
3. **주의**: HTML은 완전 인라인 CSS만 사용 (외부 CSS 불가, 이메일 호환 위해)

## Q5. AI 요약이 안 되면?

1. `.streamlit/secrets.toml`에 API 키가 있는지 확인
2. Streamlit Cloud라면 Settings → Secrets에서 확인
3. API 키 없으면 버튼이 비활성화되며, 앱 자체는 정상 동작

## Q6. 예산 게이지가 이상하게 표시되면?

예산 모델:
- 1 블로그건 = 200,000원 (`_BLOG_UNIT_KRW`)
- 이월 1건 = 0.5 치환건
- 디자인 이월: 10만원 = 1 치환건

이 상수값이 변경되면 `app.py`의 `_BLOG_UNIT_KRW`와 이월 계산 로직 수정 필요

## Q7. 브랜치 전략은?

현재 `main` 브랜치 단일 운영. push 즉시 배포됩니다.
안전하게 하려면 `develop` 브랜치를 만들어 테스트 후 main에 병합 권장.

## Q8. 피드백 보고서는?

별도 모드로 동작합니다:
- **프로세서**: `src/processors/feedback.py`
- **HTML 생성**: `src/reporting/feedback_report.py`
- 고객 피드백 데이터를 분석하는 별도 보고서

## Q9. Claude Code로 개발할 때 팁은?

이 프로젝트는 Claude Code(CLI)로 개발되었습니다:
- 커밋 메시지에 `Co-Authored-By: Claude Opus 4.6` 포함
- 코드 수정 전 항상 해당 줄을 먼저 읽기 (`Read` 도구 사용)
- `py_compile`로 검증 후 커밋
- 함수 재정의 패턴 주의 — grep으로 마지막 정의 확인

## Q10. 향후 개선 추천 사항은?

1. **app.py 분리**: 정책 사전 → `config/policies.py`, 팀 플로우 → `src/ui/proposal_flow.py`
2. **테스트 코드 추가**: 프로세서별 단위 테스트
3. **타입 힌트 보강**: 현재 부분적으로만 적용됨
4. **함수 재정의 정리**: 동일 함수 중복 정의 제거, 최종 버전만 유지
5. **데이터 검증**: 업로드 파일 스키마 검증 강화
6. **다국어 지원**: 현재 한국어 하드코딩, 템플릿 기반으로 전환 가능
