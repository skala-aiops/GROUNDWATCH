# 2026-10-08 문서 통합 검수

현행 기준 문서는 README·AGENTS·TODO·proposal·팀 안내·운영·API 계약·데이터 설명·증거 안내의 9개로 정리했습니다. 기존 사용법·설계·검토 문서와 수정 전 TODO·기획서·계약은 docs/archive/2026-10-08-before-cleanup에 보존했습니다. 이전 누적 증거 README는 같은 records 폴더의 2026-10-08.md로 이동했습니다. 기존 기록의 표현·실행 결과는 유지하고 이동 링크를 조정했습니다.

현행 9개·발표 내용 텍스트·상위 README의 로컬 링크와 heading anchor를 확인했습니다. 기획서 1~6항목·팀원 6명·역할·사진 자리, 최신 97개 테스트의 원본 로그 링크를 확인했습니다. 기능 테스트를 다시 실행한 결과로 설명하지 않습니다. Markdown diff --check 통과. 코드·데이터 원본·모델·테스트 소스와 기존 output 삭제 상태를 복원하거나 추가 변경하지 않았습니다.

PDF는 현재 v4의 15개 페이지를 보존하고 팀원 페이지를 추가해 output/final의 지정 파일명으로 저장했습니다. pypdf로 기존 15페이지 텍스트 동일·최종 16페이지·마지막 6명 확인, Poppler로 16페이지 렌더 검수 완료. 원본은 output/archive에 보존했습니다. 처음 PyMuPDF import가 없어 실패했고 설치 대신 제공된 reportlab·pypdf로 보완했습니다. 임시 스크립트·렌더 이미지는 /private/tmp에 둡니다.

정리 중 루트의 v4 PDF가 별도로 반복 생성되는 것을 확인했습니다. 해당 작업본은 output/source/working-v4.pdf로 보존하고 제출 기준은 output/final의 PDF로 한정했습니다. 발표 내용 참고 원문은 output/source/proposal.md이며 PDF 배치 편집 원본이 아닙니다. 실제 제출·발표·서비스 재배포·커밋·푸시는 이 문서 정리의 완료 범위가 아닙니다.
