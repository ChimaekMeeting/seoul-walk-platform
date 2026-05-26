# Scoring (Layer 3-1)

**목적:** Layer 1의 features와 Layer 2의 profile을 결합해서 edge cost/custom_score를 계산합니다.

**금지사항:**
- 순환/편도 경로 탐색 금지
- 오직 edge score 계산 책임만 가집니다.
