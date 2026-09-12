// 재생 화면 동작. route_view.render_player가 routes.html의 <script>에 통째로 넣는다.
//
// 이 파일은 엔진의 변수명·줄 번호를 참조하지 않는다. 읽는 것은 어댑터가 만든 공통
// 이벤트(kind·decision·focus·values)와 route_view가 만든 payload뿐이다. 화면에 쓰는
// 문구도 event.decision.reason, event.values, KIND_MEANINGS에서만 나온다 — 기록에 없는
// 판단 이유나 수치를 화면에서 만들지 않는다.
(() => {
  'use strict';

  const data = JSON.parse(document.getElementById('route-data').textContent);
  const $ = id => document.getElementById(id);
  const canvas = $('map'), ctx = canvas.getContext('2d');
  const mini = $('minimap'), mctx = mini.getContext('2d');
  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const SELFTEST = new URLSearchParams(location.search).get('selftest') === '1';

  // ── 상태 ─────────────────────────────────────────────────
  let result = null, index = 0, timer = null, timeline = [];
  let camera = null, cameraMode = 'auto', tween = null;
  let drag = null, pinch = null, lastScale = 1;
  let pathAnim = null, pathAnimResolve = null;
  // 자가 점검(?selftest=1)이 읽는 마지막 렌더 상태. 화면 동작에는 쓰지 않는다.
  const stats = {drawnPaths: 0, keptOverlay: false, minimap: null, disabledOptions: 0,
                 landmarkLabel: null, landmarkLabelSkipped: false, landmarkRayOffscreen: false};

  // ── 상수 ─────────────────────────────────────────────────
  // 자동 확대 하한(m). A* 초반에는 focus 노드가 현재 지점 주변에 몰려 있어 더 좁게 잡으면
  // 주변 도보망이 거의 안 보인다(PR #424 점검에서 25m 눈금까지 들어간 장면이 나왔다).
  const MIN_RADIUS = 200;
  // focus 노드가 이보다 적으면 최근 탐색 구간을 함께 담아 위치를 알아볼 수 있게 한다.
  const FOCUS_MIN_NODES = 3;
  const FOCUS_TREE_TAIL = 20;      // 함께 담을 최근 탐색 구간 수
  const LABEL_GAP = 22;            // 가장자리 라벨이 이보다 가까우면 겹치므로 생략한다(px)
  const FOCUS_PAD = 0.20;          // focus 노드 범위에 더하는 여백
  const FINAL_PAD = 0.15;          // 최종 경로 범위에 더하는 여백
  const TWEEN_MS = 250;            // 카메라 이동 시간 상한
  const PATH_DRAW_MS = 1800;       // 최종 경로 그리기 애니메이션 길이
  // 프레임 시계가 진행하지 않는 환경(headless 가상 시간 등)에서 애니메이션이 끝나지 않는
  // 것을 막는 상한. 실제 브라우저에서는 60fps로도 10초치라 먼저 시간이 다 찬다.
  const MAX_FRAMES = 600;

  const COLORS = {
    background: '#344257', tree: '#97ddb5', frontier: '#ffc247', candidate: '#ffc247',
    keep: '#57d7ff', reject: '#ff7a7a', before: '#f88fc1', final: '#68ff97',
    waypoint: '#d6a6ff', landmark: '#ff9f45', start: '#ff7272', end: '#ffffff',
  };
  // kind 태그: [표시 문구, 배경색]. 어휘는 visualizations/events.py의 KINDS와 같다.
  const KIND_TAGS = {
    run_start: ['시작', '#a8c7ff'], candidates: ['후보', '#ffd58a'], evaluate: ['평가', '#a9dcf6'],
    select: ['선택', '#8fe0ff'], reject: ['기각', '#ffb0b0'], route_changed: ['경로 변경', '#f9b9d8'],
    cleanup: ['정리', '#cfc0ff'], final: ['결과', '#9bf0b8'],
  };
  // visualizations/events.py의 KIND_MEANINGS와 같은 내용이다. 어휘가 바뀌면 같이 고친다.
  const KIND_MEANINGS = {
    run_start: '실행 시작. 입력과 조건을 알린다.',
    candidates: '이번 단계에서 만들어진 후보 목록.',
    evaluate: '후보를 평가했다(채택 여부는 아직 아님).',
    select: '후보를 골랐다.',
    reject: '후보를 버렸다.',
    route_changed: '현재 경로가 실제로 바뀌었다.',
    cleanup: '기존 정리 규칙을 적용했다.',
    final: '엔진이 반환한 결과.',
  };
  const SERVICE_BADGES = {service: '서비스 엔진', benchmark_only: '벤치마크 전용'};
  // 같은 A* 엔진을 휴리스틱만 바꿔 돌린 결과라 비교표에서는 한 묶음으로 본다.
  const SHORTEST_MODES = ['shortest', 'shortest_alt'];
  const EXPANDED_REASONS = {
    new: '처음 넣음', improved: '더 나은 비용으로 갱신', worse: '이미 같거나 더 나은 비용이 큐에 있음',
    stale: '이미 더 나은 경로로 확장함', blocked: '통행 차단', cutoff: '상한 초과',
  };

  // phase별 설명문(기존 유지). kind 기준 문구는 KIND_MEANINGS와 태그가 담당한다.
  const descriptions = {
    refinement_done: ['한 초기 후보의 개선 완료', '분홍색 초기 경로와 개선 과정을 마친 하늘색 경로를 비교합니다. 서로 다른 재시작 후보를 전후 변화로 섞지 않습니다.'],
    vns_decision: ['VNS · 교란 후 재개선 판단', '교란 후보를 VND로 개선한 결과(하늘색)를 기존 경로(분홍색)와 비교합니다. 기각된 하늘색 경로는 이후 현재 경로로 쓰이지 않습니다.'],
    grasp_choice: ['GRASP · 경유지 선택', '주황색 후보 중 실제로 선택된 경유지를 강조합니다. 보라색 점선은 현재 선택 순서이며, 도로 경로로 연결하기 전입니다.'],
    constructed: ['GRASP · 초기 경로 생성', '선택한 경유지를 실제 도보망에서 연결해 만든 초기 경로입니다.'],
    construction_failed: ['GRASP · 초기 경로 생성 실패', '이번 경유지 선택으로 유효한 초기 경로를 만들지 못했습니다. 다음 재시작으로 넘어갑니다.'],
    neighbor: ['지역 개선 · 후보 검토', '현재 경로(분홍색)에서 경유지를 바꾼 후보(하늘색)를 검토합니다. 아직 채택된 결과는 아닙니다.'],
    improved: ['지역 개선 · 변경 채택', '실제 비교 기준에서 개선된 후보를 현재 경로로 채택했습니다.'],
    winner: ['전체 최선 경로 갱신', '지금까지 만든 결과 중 가장 좋은 경로가 바뀌었습니다.'],
    shake: ['VNS · 경로 교란', '현재 경로를 바꿔 새로운 지역을 탐색합니다. 이어서 VND로 다시 개선합니다.'],
    shake_failed: ['VNS · 교란 실패', '이 교란 방식으로 유효한 후보를 만들지 못했습니다. 다음 시도를 진행합니다.'],
    destroy: ['ALNS · 일부 경유지 제거', '이전 경유지 순서에서 일부를 제거했습니다. 도로 경로가 아닌 경유지 순서를 점선으로 표시합니다.'],
    repair: ['ALNS · 경유지 재삽입', '제거한 자리를 새로운 후보로 채워 경유지 순서를 만들었습니다. 아직 서비스의 최종 경로가 아닙니다.'],
    alns_accept: ['ALNS · 내부 수락 판단', 'ALNS 내부 비용·온도 규칙의 판단입니다. 나쁜 후보를 일시적으로 받아들일 수 있고, 최선해는 별도로 보존합니다.'],
    alns_result: ['ALNS · 실제 경로 재검증', 'ALNS 결과를 도로 경로로 연결하고 기존 경로와 비교합니다. 경유지 간격과 재통행 등을 확인해 최종적으로 반영하거나 기존 경로를 유지합니다.'],
    start: ['출발 준비', '출발점과 도착점을 도보망에 연결했습니다. 재생을 누르면 실제 탐색 기록을 순서대로 볼 수 있습니다.'],
    astar: ['A* · 다음 지점 확인', '도착지까지의 예상 비용을 기준으로 우선순위 큐에서 지점을 꺼냅니다. 파란 점이 이번 지점, 주황색은 대기 중인 지점입니다. 이미 더 좋은 경로가 있으면 꺼낸 항목을 건너뛸 수도 있습니다.'],
    expand: ['Beam · 후보 확장', '남겨 둔 각 경로의 끝에서 이웃 길로 한 단계씩 확장했습니다. 주황색 선은 이번에 만들어진 후보 경로입니다.'],
    drop: ['Beam · 탈락 후보', '같은 확장에서 만들어졌지만 평가값 순위가 상위 k개 밖이라 버린 후보입니다. 붉은 점선이 탈락 후보, 얇은 하늘색이 같은 반복에서 유지된 경로입니다.'],
    keep: ['Beam · 상위 후보 유지', '기존 엔진의 정렬 기준으로 상위 최대 8개 경로를 남겼습니다. 파란 선이 다음 탐색으로 이어질 후보입니다.'],
    connect: ['도착점으로 연결', '한 후보의 끝에서 도착점까지 연결한 완성 경로입니다. 순환은 상명대로 돌아갑니다. 아직 최종 선택된 경로는 아닙니다.'],
    selection: ['완성 후보 선택', '도착점 연결에 성공한 후보를 비교한 뒤 최대 3개를 골랐습니다. 다음 단계에서 기존 정리 규칙을 적용합니다.'],
    prune: ['기존 정리 규칙 적용', '분홍색은 정리 전, 파란색은 정리 후입니다. 현재 코드는 반복 노드 사이의 짧은 구간을 제거하므로, 정리 후 목표 거리에서 멀어질 수도 있습니다.'],
    final: ['반환 결과', '초록색은 엔진이 실제 반환한 경로입니다. 굵은 선은 대표 후보, 옅은 선은 추가 후보입니다. 목표 거리 충족 여부는 오른쪽 결과를 확인하세요.'],
  };

  // ── 값 표시 도우미 ───────────────────────────────────────
  const km = v => (v / 1000).toFixed(3) + ' km';
  const pct = v => (v * 100).toFixed(1) + '%';
  const meters = v => v == null ? '—' : Math.round(v) + ' m';
  const seconds = v => v == null ? '미측정' : v < 1 ? (v * 1000).toFixed(1) + ' ms' : v.toFixed(3) + ' s';
  const stripBadge = text => Object.values(SERVICE_BADGES)
    .reduce((t, badge) => t.replace(' · ' + badge, ''), text || '');
  const rowName = r => r.mode === 'circular' ? '순환 Beam'
    : SHORTEST_MODES.includes(r.mode) && r.settings ? r.engine + ' · ' + stripBadge(r.settings)
    : r.engine;
  const currentEvent = () => result.trace[timeline[index]];

  // ── 선택 화면 ────────────────────────────────────────────
  function buildPickers() {
    data.cases.forEach((item, i) => {
      const option = document.createElement('option');
      option.value = i;
      option.textContent = item.request;
      $('scenario').append(option);
    });
    const select = $('algorithm');
    const known = new Set();
    let disabled = 0;
    const rerun = [];
    (data.catalog || []).forEach(entry => {
      known.add(entry.mode);
      const option = document.createElement('option');
      option.value = entry.mode;
      const produced = data.results.find(r => r.mode === entry.mode);
      if (entry.available && produced) {
        option.textContent = (produced.label || entry.label) + (produced.settings ? ' · ' + produced.settings : '');
      } else {
        // 이 파일에 결과가 없는 항목. 고를 수 없고, 새 실행 명령만 알려 준다.
        option.textContent = entry.label + ' · 새 실행 필요';
        option.disabled = true;
        disabled++;
        rerun.push(entry);
      }
      select.append(option);
    });
    // catalog에 없는 결과가 들어와도 고를 수 있게 남긴다(목록이 낡아도 화면이 막히지 않는다).
    data.results.filter(r => !known.has(r.mode)).forEach(r => {
      const option = document.createElement('option');
      option.value = r.mode;
      option.textContent = (r.label || r.mode) + (r.settings ? ' · ' + r.settings : '');
      select.append(option);
    });
    stats.disabledOptions = disabled;
    if (rerun.length) {
      const commands = [...new Set(rerun.map(entry => entry.command))];
      $('rerun-note').textContent = '이 파일에 결과가 없는 ' + rerun.length + '개: '
        + rerun.map(entry => entry.label).join(', ')
        + '. 아래 명령을 직접 실행해 새 결과를 만든 뒤 새 routes.html을 여세요(이 화면은 실행하지 않습니다).';
      $('rerun-command').textContent = commands.join('  /  ');
      $('rerun').hidden = false;
    }
    const summary = data.scenario || {};
    const rows = [['시나리오', summary.name || summary.id || '—'], ['출발', summary.origin || '—'],
                  ['도착', summary.destination || '—']];
    $('scenario-summary').replaceChildren(...rows.flatMap(([key, value]) => {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = key; dd.textContent = value;
      return [dt, dd];
    }));
  }

  function conditionRows(item) {
    const c = item.conditions || {};
    const heuristic = c.heuristic || {}, config = c.config || {}, artifact = c.artifact || {};
    const rows = [['엔진', c.engine_class || item.engine], ['알고리즘', c.algorithm || '—']];
    if (heuristic.name) {
      rows.push(['휴리스틱', heuristic.name + (heuristic.method ? ' · ' + heuristic.method : '')]);
      if (heuristic.k_requested != null) {
        rows.push(['랜드마크 수', '요청 ' + heuristic.k_requested + ' · 실제 ' + heuristic.k_actual]);
      }
    }
    rows.push(['목표 거리', c.target_m != null ? meters(c.target_m) : '없음']);
    rows.push(['seed', c.seed != null ? String(c.seed) : '—']);
    if (config.num_waypoints != null) rows.push(['경유지 수', String(config.num_waypoints)]);
    if (config.grasp_iters != null) rows.push(['재시작 수', String(config.grasp_iters)]);
    if (config.refinement) rows.push(['정제', config.refinement]);
    rows.push(['서비스 연결', SERVICE_BADGES[c.service_use] || '미기록']);
    if (c.code_commit) rows.push(['코드', c.code_commit.slice(0, 7)]);
    if (artifact.data_version) rows.push(['도보망', artifact.data_version]);
    return rows;
  }

  function renderConditions() {
    $('conditions-table').replaceChildren(...conditionRows(result).map(([key, value]) => {
      const tr = document.createElement('tr');
      [key, value].forEach(text => {
        const td = document.createElement('td');
        td.textContent = text;
        tr.append(td);
      });
      return tr;
    }));
    $('algorithm-note').textContent = (result.label || result.mode) + ' · ' + (result.settings || '');
  }

  // ── 비교표 ───────────────────────────────────────────────
  function comparisonRows() {
    const circular = result.start.node === result.end.node;
    const shortest = SHORTEST_MODES.includes(result.mode);
    return data.results.filter(r => circular
      ? r.start.node === r.end.node && r.target_m === result.target_m
      : shortest ? SHORTEST_MODES.includes(r.mode) : r.mode === result.mode);
  }

  function conditionWarning(rows) {
    // 실행 조건이 다른 행은 route_view가 미리 계산한 condition_diff에서만 찾는다.
    const diff = (data.condition_diff || {})[result.mode] || {};
    const labels = data.condition_labels || {};
    const different = rows.filter(r => r.mode !== result.mode && diff[r.mode]);
    if (!different.length) {
      $('condition-warning').hidden = true;
      return 0;
    }
    $('condition-warning').textContent = '실행 조건이 다른 행: '
      + different.map(r => rowName(r) + '(' + diff[r.mode].map(f => labels[f] || f).join('·') + ' 다름)').join(', ')
      + ' (같은 조건으로 비교하지 마세요)';
    $('condition-warning').hidden = false;
    return different.length;
  }

  function comparison() {
    const circular = result.start.node === result.end.node;
    const shortest = SHORTEST_MODES.includes(result.mode);
    const rows = comparisonRows();
    $('comparison-title').textContent = circular ? '상명대 ' + km(result.target_m) + ' 순환 · 결과 비교'
      : shortest ? '상명대 → 경복궁역 · 최단거리 결과' : '상명대 → 경복궁역 · 편도 우회 결과';
    $('comparison-body').replaceChildren();
    rows.forEach(r => {
      const m = r.metrics[0], tr = document.createElement('tr');
      tr.className = r.mode === result.mode ? 'selected' : '';
      const cells = [
        rowName(r),
        SERVICE_BADGES[(r.conditions || {}).service_use] || '미기록',
        seconds(r.run_seconds),
        m ? km(m.distance_m) : '경로 없음',
        m?.target_error_m != null ? m.target_error_m.toFixed(1) + ' m' : '해당 없음',
        !r.route_valid ? '경로 검증 실패'
          : m?.target_within_tolerance == null ? 'Dijkstra 일치'
          : (m.target_within_tolerance ? '범위 안' : '범위 밖') + ' (±' + Math.round(r.tolerance_ratio * 100) + '%)',
        m ? pct(m.repeated_edge_ratio) : '—',
      ];
      cells.forEach((value, i) => {
        const td = document.createElement('td');
        td.textContent = value;
        if (i === 5 && (!r.route_valid || m?.target_within_tolerance === false)) td.className = 'warning';
        tr.append(td);
      });
      const td = document.createElement('td'), button = document.createElement('button');
      button.textContent = '과정 보기';
      button.setAttribute('aria-label', cells[0] + ' 과정 보기');
      button.onclick = () => selectResult(r.mode);
      td.append(button);
      tr.append(td);
      $('comparison-body').append(tr);
    });
    conditionWarning(rows);
    const configured = rows.find(r => r.mode.startsWith('grasp_') && r.settings);
    const heuristics = rows.filter(r => SHORTEST_MODES.includes(r.mode) && r.settings)
      .map(r => stripBadge(r.settings)).join(' / ');
    $('comparison-settings').textContent =
      (configured ? 'GRASP 계열: ' + configured.settings + ' · 같은 seed여도 개선 과정의 난수 소비로 이후 초기 후보는 달라질 수 있습니다. ' : '')
      + (heuristics ? '휴리스틱 조건: ' + heuristics + ' · 둘 다 admissible이라 반환 경로는 같고 탐색량만 달라집니다. ' : '')
      + '재통행 = 이미 지난 무방향 엣지를 다시 걷는 거리 / 전체 거리. 목표 범위 안에서도 오차와 재통행을 함께 보세요.';
  }

  // ── 카메라 ───────────────────────────────────────────────
  function boundsOf(coords) {
    if (!coords.length) return null;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of coords) {
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    return {minX, maxX, minY, maxY};
  }

  function cameraFor(coords, pad) {
    const box = boundsOf(coords);
    if (!box) return null;
    const span = Math.max(box.maxX - box.minX, box.maxY - box.minY);
    const radius = Math.max(span / 2 * (1 + pad), MIN_RADIUS);
    return {cx: (box.minX + box.maxX) / 2, cy: (box.minY + box.maxY) / 2,
            radius: Math.min(radius, result.bounds.radius)};
  }

  const coordsOf = ids => (ids || []).map(n => data.nodes[n]).filter(Boolean);

  // 한 점에서 angle 방향으로 나간 반직선이 화면 사각형과 만나는 자리. 없으면 null.
  function edgeCrossing(from, angle, w, h) {
    const dx = Math.cos(angle), dy = Math.sin(angle);
    let nearest = Infinity;
    const consider = t => { if (t > 0 && t < nearest) nearest = t; };
    if (dx > 1e-9) consider((w - from[0]) / dx);
    if (dx < -1e-9) consider((0 - from[0]) / dx);
    if (dy > 1e-9) consider((h - from[1]) / dy);
    if (dy < -1e-9) consider((0 - from[1]) / dy);
    return Number.isFinite(nearest) ? [from[0] + dx * nearest, from[1] + dy * nearest] : null;
  }

  function autoTarget(event) {
    // 시작은 전체 범위, 최종은 반환 경로 범위, 나머지는 어댑터가 남긴 focus.nodes.
    if (event.kind === 'run_start') return {...result.bounds};
    if (event.kind === 'final') {
      const coords = [];
      event.paths.forEach(path => coordsOf(path).forEach(p => coords.push(p)));
      return cameraFor(coords, FINAL_PAD) || {...result.bounds};
    }
    const ids = [...((event.focus && event.focus.nodes) || [])];
    if (ids.length < FOCUS_MIN_NODES) {
      // 화면 규칙일 뿐 이벤트 데이터는 바꾸지 않는다. 탐색 트리의 끝점(child) 쪽만 쓴다.
      (event.tree || []).slice(-FOCUS_TREE_TAIL).forEach(edge => {
        if (edge.length > 1) ids.push(edge[1]);
      });
    }
    return cameraFor(coordsOf(ids), FOCUS_PAD);
  }

  function tweenMs() {
    if (REDUCED) return 0;
    // 재생 중에는 장면 간격보다 짧게 끝나야 다음 장면과 겹치지 않는다.
    return timer !== null ? Math.min(TWEEN_MS, Number($('speed').value) * 0.7) : TWEEN_MS;
  }

  function moveCamera(target, animate, done) {
    tween = null;
    if (!animate || REDUCED || !camera) {
      camera = {...target};
      draw();
      if (done) done();
      return;
    }
    tween = {from: {...camera}, to: {...target}, started: performance.now(), ms: tweenMs(), done, frames: 0};
    if (!tween.ms) {
      camera = {...target};
      tween = null;
      draw();
      if (done) done();
      return;
    }
    requestAnimationFrame(stepTween);
  }

  function stepTween(now) {
    if (!tween) return;
    tween.frames++;
    const t = tween.frames >= MAX_FRAMES ? 1 : Math.max(0, Math.min(1, (now - tween.started) / tween.ms));
    const eased = 1 - Math.pow(1 - t, 3);            // ease-out
    const mix = (a, b) => a + (b - a) * eased;
    camera = {cx: mix(tween.from.cx, tween.to.cx), cy: mix(tween.from.cy, tween.to.cy),
              radius: mix(tween.from.radius, tween.to.radius)};
    draw();
    if (t < 1) {
      requestAnimationFrame(stepTween);
    } else {
      const done = tween.done;
      tween = null;
      if (done) done();
    }
  }

  function setManual(on) {
    cameraMode = on ? 'manual' : 'auto';
    $('camera-note').classList.toggle('on', on);
    if (!on) applyCamera(currentEvent(), true);
  }

  function applyCamera(event, animate, done) {
    if (cameraMode !== 'auto') {
      draw();
      if (done) done();
      return;
    }
    const target = autoTarget(event);
    if (!target) {              // focus가 비어 있으면 카메라를 유지한다.
      draw();
      if (done) done();
      return;
    }
    moveCamera(target, animate, done);
  }

  // ── 최종 경로 그리기 애니메이션 ──────────────────────────
  function cancelPathAnimation() {
    pathAnim = null;
    if (pathAnimResolve) {
      pathAnimResolve();
      pathAnimResolve = null;
    }
  }

  function startPathAnimation() {
    cancelPathAnimation();
    const event = currentEvent();
    const nodes = (event.paths[0] || []).filter(n => data.nodes[n]);
    if (nodes.length < 2) {
      pathAnim = {nodes: [], cumulative: [], total: 0, progress: 1, done: true};
      draw();
      return Promise.resolve();
    }
    const cumulative = [0];
    for (let i = 1; i < nodes.length; i++) {
      const a = data.nodes[nodes[i - 1]], b = data.nodes[nodes[i]];
      cumulative.push(cumulative[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1]));
    }
    pathAnim = {nodes, cumulative, total: cumulative[cumulative.length - 1],
                started: performance.now(), ms: REDUCED ? 0 : PATH_DRAW_MS,
                progress: REDUCED ? 1 : 0, done: REDUCED, frames: 0};
    if (REDUCED) {
      draw();
      return Promise.resolve();
    }
    const promise = new Promise(resolve => { pathAnimResolve = resolve; });
    requestAnimationFrame(stepPath);
    return promise;
  }

  function stepPath(now) {
    if (!pathAnim || pathAnim.done) return;
    // requestAnimationFrame이 넘기는 시각은 직전에 읽은 performance.now()보다 앞설 수 있다.
    // 그대로 쓰면 진행률이 음수가 되므로 0~1로 자른다.
    pathAnim.frames++;
    pathAnim.progress = pathAnim.frames >= MAX_FRAMES ? 1
      : Math.max(0, Math.min(1, (now - pathAnim.started) / pathAnim.ms));
    draw();
    if (pathAnim.progress < 1) {
      requestAnimationFrame(stepPath);
    } else {
      pathAnim.done = true;
      draw();
      if (pathAnimResolve) {
        pathAnimResolve();
        pathAnimResolve = null;
      }
    }
  }

  // 자가 점검용. 프레임 시계가 멈춘 환경에서도 같은 상태 전이를 그대로 밟게 한다.
  function finishPathAnimation() {
    if (pathAnim && !pathAnim.done) stepPath(pathAnim.started + pathAnim.ms);
  }

  // 거리 비례로 잘라 낸 대표 후보 노드열(+ 마지막 구간의 중간점).
  function animatedPath() {
    const reached = pathAnim.total * pathAnim.progress;
    const coords = [];
    for (let i = 0; i < pathAnim.nodes.length; i++) {
      if (i === 0 || pathAnim.cumulative[i] <= reached) {
        coords.push(data.nodes[pathAnim.nodes[i]]);
        continue;
      }
      const a = data.nodes[pathAnim.nodes[i - 1]], b = data.nodes[pathAnim.nodes[i]];
      const span = pathAnim.cumulative[i] - pathAnim.cumulative[i - 1];
      const t = span ? (reached - pathAnim.cumulative[i - 1]) / span : 0;
      coords.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
      break;
    }
    return coords;
  }

  // ── 그리기 ───────────────────────────────────────────────
  // reject 장면에서 함께 그릴 "같은 반복의 유지 후보". 직전 select 이벤트에서만 가져오고,
  // 없으면 그리지 않는다(없는 후보를 만들어 그리지 않는다).
  function keptBeside(event, absolute) {
    if (event.kind !== 'reject') return null;
    const iteration = event.values && event.values.iteration;
    if (iteration == null) return null;
    for (let i = absolute - 1; i >= 0 && i >= absolute - 4; i--) {
      const other = result.trace[i];
      if (other.kind === 'select' && other.values && other.values.iteration === iteration) return other.paths;
      if (other.kind === 'candidates') break;
    }
    return null;
  }

  function draw() {
    if (!result || !camera) return;
    const absolute = timeline[index], event = result.trace[absolute];
    const box = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * dpr);
    canvas.height = Math.round(box.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = box.width, h = box.height, pad = 40;
    const scale = (Math.min(w, h) - pad * 2) / (camera.radius * 2);
    lastScale = scale;
    const xy = p => [w / 2 + (p[0] - camera.cx) * scale, h / 2 - (p[1] - camera.cy) * scale];
    const point = n => xy(data.nodes[n]);
    let drawn = 0;

    ctx.fillStyle = '#090f1a';
    ctx.fillRect(0, 0, w, h);
    function line(coords, color, width = 1, alpha = 1, dash = null) {
      if (!coords.length) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.globalAlpha = alpha;
      if (dash) ctx.setLineDash(dash);
      ctx.beginPath();
      coords.forEach((p, i) => {
        const q = xy(p);
        if (i) ctx.lineTo(q[0], q[1]); else ctx.moveTo(q[0], q[1]);
      });
      ctx.stroke();
      ctx.globalAlpha = 1;
      if (dash) ctx.setLineDash([]);
    }
    function path(nodes, color, width = 1, alpha = 1, dash = null) {
      const coords = coordsOf(nodes);
      if (coords.length) drawn++;
      line(coords, color, width, alpha, dash);
    }
    function dot(n, color, r = 2) {
      if (!data.nodes[n]) return;
      const p = point(n);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p[0], p[1], r, 0, 2 * Math.PI);
      ctx.fill();
    }
    function label(text, x, y, color) {
      ctx.lineWidth = 4;
      ctx.strokeStyle = '#090f1a';
      ctx.strokeText(text, x, y);
      ctx.fillStyle = color;
      ctx.fillText(text, x, y);
    }

    data.background.forEach(s => line(s, COLORS.background, .8));

    const isFinal = event.kind === 'final', isStart = event.kind === 'run_start';
    // 최종 장면은 이전 장면의 후보·대기 지점·탐색 트리를 절대 함께 그리지 않는다.
    if (!isFinal && !isStart) {
      (event.tree || []).forEach(edge => line(coordsOf(edge), COLORS.tree, 2));
      (event.frontier || []).forEach(n => dot(n, COLORS.frontier, 3));
      (event.choices || []).forEach(n => dot(n, COLORS.frontier, 5));
      if (event.before) path(event.before, COLORS.before, 5, .8);
    }

    stats.keptOverlay = false;
    stats.landmarkLabel = null;
    stats.landmarkLabelSkipped = false;
    stats.landmarkRayOffscreen = false;
    if (isStart) {
      // 시작 장면은 입력만 알린다. 아직 아무것도 탐색하지 않았으므로 경로를 그리지 않는다.
    } else if (isFinal) {
      if (pathAnim) {
        line(animatedPath(), COLORS.final, 3.6);
        drawn++;
        if (pathAnim.done) event.paths.slice(1).forEach(p => path(p, COLORS.final, 2, .5));
      } else {
        event.paths.forEach((p, i) => path(p, COLORS.final, i === 0 ? 3.3 : 2, i === 0 ? 1 : .5));
      }
    } else if (event.kind === 'reject') {
      const kept = keptBeside(event, absolute);
      if (kept) {
        kept.forEach(p => path(p, COLORS.keep, 1.4, .75));
        stats.keptOverlay = true;
      }
      event.paths.forEach(p => path(p, COLORS.reject, 2.2, .95, [5, 5]));
    } else {
      // 후보 생성은 주황, 선택·평가·경로 변경·정리는 하늘색. 평가는 "아직 채택 아님"이라 가늘게.
      const shade = event.kind === 'candidates' ? COLORS.candidate : COLORS.keep;
      const thin = event.kind === 'evaluate';
      event.paths.forEach((p, i) => path(p, shade, i === 0 ? (thin ? 1.8 : 3.3) : 2, i === 0 ? 1 : .65));
    }

    if (!isFinal && !isStart && event.previous_waypoints) {
      line(coordsOf([result.start.node, ...event.previous_waypoints, result.end.node]), COLORS.before, 2, 1, [4, 6]);
    }
    if (!isFinal && !isStart && event.waypoints) {
      if (!event.paths.length) {
        line(coordsOf([result.start.node, ...event.waypoints, result.end.node]), COLORS.waypoint, 2, 1, [5, 7]);
      }
      ctx.font = 'bold 13px system-ui';
      ctx.textAlign = 'left';
      event.waypoints.forEach((n, i) => {
        dot(n, COLORS.waypoint, 6);
        if (!data.nodes[n]) return;
        const p = point(n);
        ctx.fillStyle = '#f5eaff';
        ctx.fillText('W' + (i + 1), p[0] + 9, p[1] + 16);
      });
    }

    // ALT 랜드마크는 화면 범위 계산에서 빠져 있으므로 지금 보이는 영역 안일 때만 그린다.
    (result.landmarks || []).forEach(p => {
      const q = xy(p);
      if (q[0] < 0 || q[0] > w || q[1] < 0 || q[1] > h) return;
      ctx.fillStyle = COLORS.landmark;
      ctx.beginPath();
      ctx.moveTo(q[0], q[1] - 6);
      ctx.lineTo(q[0] + 6, q[1]);
      ctx.lineTo(q[0], q[1] + 6);
      ctx.lineTo(q[0] - 6, q[1]);
      ctx.closePath();
      ctx.fill();
    });

    const values = event.values || {};
    if (!isFinal && event.current !== undefined) {
      dot(event.current, COLORS.keep, values.f_m != null ? 11 : 9);
      dot(event.current, '#fff', values.f_m != null ? 5 : 4);
      if (values.f_m != null && data.nodes[event.current]) {
        // 대기 상위 후보의 f 값을 지도 위에 바로 붙인다. 겹치면 생략한다.
        ctx.font = '12px system-ui';
        ctx.textAlign = 'left';
        const placed = [];
        (values.frontier_top || []).forEach(item => {
          if (!data.nodes[item.node]) return;
          const q = point(item.node);
          if (placed.some(p => Math.hypot(p[0] - q[0], p[1] - q[1]) < 34)) return;
          placed.push(q);
          label('f ' + meters(item.f_m), q[0] + 7, q[1] - 6, '#ffd9a8');
        });
        // ALT면 하한이 가장 큰 랜드마크 방향을 현재 지점에서 얇은 점선으로 가리킨다.
        if (values.h_kind === 'alt' && values.best_landmark != null) {
          const target = landmarkCoordFor(values.best_landmark);
          if (target) {
            const from = point(event.current), to = xy(target);
            const angle = Math.atan2(to[1] - from[1], to[0] - from[0]);
            const full = Math.hypot(to[0] - from[0], to[1] - from[1]);
            const reach = Math.min(full, Math.max(w, h));
            const tip = [from[0] + Math.cos(angle) * reach, from[1] + Math.sin(angle) * reach];
            ctx.setLineDash([3, 6]);
            ctx.strokeStyle = COLORS.landmark;
            ctx.lineWidth = 1;
            ctx.globalAlpha = .8;
            ctx.beginPath();
            ctx.moveTo(from[0], from[1]);
            ctx.lineTo(tip[0], tip[1]);
            ctx.stroke();
            ctx.globalAlpha = 1;
            ctx.setLineDash([]);
            // 랜드마크가 화면 밖이면 점선이 가장자리와 만나는 자리에 방향과 거리를 적는다.
            if (tip[0] < 0 || tip[0] > w || tip[1] < 0 || tip[1] > h || full > reach) {
              stats.landmarkRayOffscreen = true;
              const edge = edgeCrossing(from, angle, w, h);
              if (edge && placed.some(q => Math.hypot(q[0] - edge[0], q[1] - edge[1]) < LABEL_GAP)) {
                stats.landmarkLabelSkipped = true;
              } else if (edge) {
                placed.push(edge);
                const away = Math.hypot(target[0] - data.nodes[event.current][0],
                                        target[1] - data.nodes[event.current][1]) / 1000;
                const text = 'L' + values.best_landmark + ' 방향 · ' + away.toFixed(1) + 'km';
                ctx.font = '12px system-ui';
                ctx.textAlign = edge[0] > w * .7 ? 'right' : 'left';
                label(text, Math.min(Math.max(edge[0], 8), w - 8),
                      Math.min(Math.max(edge[1], 16), h - 8), COLORS.landmark);
                ctx.textAlign = 'left';
                stats.landmarkLabel = text;
              }
            }
          }
        }
      }
    }

    const same = result.start.node === result.end.node;
    const markers = [[result.start.node, COLORS.start, same ? '상명대 · 출발/복귀' : '상명대 · 출발']];
    if (!same) markers.push([result.end.node, COLORS.end, '경복궁역 3번 · 도착']);
    markers.forEach(([n, color, text]) => {
      dot(n, '#090f1a', 9);
      dot(n, color, 6);
      if (!data.nodes[n]) return;
      const p = point(n);
      ctx.font = 'bold 14px system-ui';
      ctx.textAlign = p[0] > w * .65 ? 'right' : 'left';
      label(text, p[0] + (ctx.textAlign === 'right' ? -10 : 10), Math.max(18, p[1] - 12), color);
    });
    ctx.textAlign = 'left';

    if (event.kind === 'run_start') drawRequestBox(w);

    const barMeters = camera.radius > 1000 ? 500 : camera.radius > 200 ? 100 : 25;
    ctx.strokeStyle = '#cbdcf5';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(16, h - 22);
    ctx.lineTo(16 + barMeters * scale, h - 22);
    ctx.stroke();
    ctx.fillStyle = '#cbdcf5';
    ctx.font = '12px system-ui';
    ctx.fillText(barMeters + 'm · 북쪽 ↑', 16, h - 29);

    stats.drawnPaths = drawn;
    drawMinimap(isFinal ? event : null);
    updatePanel(event, absolute);
  }

  function landmarkCoordFor(node) {
    const list = ((result.conditions || {}).heuristic || {}).landmarks || [];
    const at = list.findIndex(item => item.node === node);
    return at >= 0 ? (result.landmarks || [])[at] : null;
  }

  // run_start 장면에만 그리는 "요청 조건" 상자. 값은 전부 conditions·payload에서 온다.
  function drawRequestBox(w) {
    const c = result.conditions || {}, heuristic = c.heuristic || {};
    const lines = [result.label || result.mode,
      '목표 ' + (result.target_m != null ? km(result.target_m) : '없음(최단거리)'),
      '휴리스틱 ' + (heuristic.name || '—'),
      SERVICE_BADGES[c.service_use] || '미기록'];
    ctx.font = '13px system-ui';
    ctx.textAlign = 'left';
    const width = Math.min(Math.max(...lines.map(t => ctx.measureText(t).width)) + 22, w - 32);
    ctx.fillStyle = 'rgba(26,38,56,.92)';
    ctx.strokeStyle = '#43516a';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect(16, 16, width, lines.length * 19 + 16, 8);
    ctx.fill();
    ctx.stroke();
    lines.forEach((text, i) => {
      ctx.fillStyle = i === 0 ? '#eff6ff' : '#a6b7d0';
      ctx.fillText(text, 27, 36 + i * 19);
    });
  }

  // ── 미니맵 ───────────────────────────────────────────────
  function drawMinimap(finalEvent) {
    const box = mini.getBoundingClientRect();
    if (!box.width) return;
    const dpr = window.devicePixelRatio || 1;
    mini.width = Math.round(box.width * dpr);
    mini.height = Math.round(box.height * dpr);
    mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = box.width, h = box.height, bounds = result.bounds;
    const scale = (Math.min(w, h) - 10) / (bounds.radius * 2);
    const xy = p => [w / 2 + (p[0] - bounds.cx) * scale, h / 2 - (p[1] - bounds.cy) * scale];
    mctx.clearRect(0, 0, w, h);
    mctx.fillStyle = 'rgba(9,15,26,.86)';
    mctx.fillRect(0, 0, w, h);
    // 배경 도보망은 간격을 넓혀 그린다 — 미니맵에서는 전체 형태만 보이면 된다.
    mctx.strokeStyle = '#2b3a52';
    mctx.lineWidth = .6;
    mctx.beginPath();
    for (let i = 0; i < data.background.length; i += 4) {
      data.background[i].forEach((p, j) => {
        const q = xy(p);
        if (j) mctx.lineTo(q[0], q[1]); else mctx.moveTo(q[0], q[1]);
      });
    }
    mctx.stroke();
    if (finalEvent) {
      mctx.strokeStyle = COLORS.final;
      mctx.lineWidth = 1.6;
      mctx.beginPath();
      coordsOf(finalEvent.paths[0] || []).forEach((p, i) => {
        const q = xy(p);
        if (i) mctx.lineTo(q[0], q[1]); else mctx.moveTo(q[0], q[1]);
      });
      mctx.stroke();
    }
    [[result.start.node, COLORS.start], [result.end.node, COLORS.end]].forEach(([n, color]) => {
      if (!data.nodes[n]) return;
      const q = xy(data.nodes[n]);
      mctx.fillStyle = color;
      mctx.beginPath();
      mctx.arc(q[0], q[1], 3, 0, 2 * Math.PI);
      mctx.fill();
    });
    // 범위 밖 랜드마크는 방향과 거리만 가장자리에 표시한다(미니맵을 넓히지 않는다).
    mctx.font = '10px system-ui';
    const labelled = [];   // 가장자리 글자가 겹치면 화살표만 남기고 거리 표시는 생략한다.
    (result.landmarks || []).forEach((p, i) => {
      const q = xy(p);
      const inside = q[0] >= 0 && q[0] <= w && q[1] >= 0 && q[1] <= h;
      if (inside) {
        mctx.fillStyle = COLORS.landmark;
        mctx.beginPath();
        mctx.moveTo(q[0], q[1] - 4);
        mctx.lineTo(q[0] + 4, q[1]);
        mctx.lineTo(q[0], q[1] + 4);
        mctx.lineTo(q[0] - 4, q[1]);
        mctx.closePath();
        mctx.fill();
        return;
      }
      const angle = Math.atan2(q[1] - h / 2, q[0] - w / 2);
      const edge = Math.min(w, h) / 2 - 12;
      const ex = w / 2 + Math.cos(angle) * edge, ey = h / 2 + Math.sin(angle) * edge;
      mctx.save();
      mctx.translate(ex, ey);
      mctx.rotate(angle);
      mctx.fillStyle = COLORS.landmark;
      mctx.beginPath();
      mctx.moveTo(5, 0);
      mctx.lineTo(-4, 3.5);
      mctx.lineTo(-4, -3.5);
      mctx.closePath();
      mctx.fill();
      mctx.restore();
      if (labelled.some(q => Math.hypot(q[0] - ex, q[1] - ey) < LABEL_GAP)) return;
      labelled.push([ex, ey]);
      const away = Math.hypot(p[0] - bounds.cx, p[1] - bounds.cy) / 1000;
      mctx.fillStyle = '#ffd9a8';
      mctx.textAlign = ex > w / 2 ? 'right' : 'left';
      mctx.fillText('L' + (i + 1) + ' · ' + away.toFixed(1) + 'km', ex + (ex > w / 2 ? -8 : 8), ey + 3);
    });
    // 지금 보고 있는 영역
    const half = camera.radius * scale;
    const centre = xy([camera.cx, camera.cy]);
    mctx.strokeStyle = '#8fe0ff';
    mctx.lineWidth = 1.2;
    mctx.strokeRect(centre[0] - half, centre[1] - half, half * 2, half * 2);
    stats.minimap = {cx: camera.cx, cy: camera.cy, radius: camera.radius};
  }

  // ── 설명 패널 ────────────────────────────────────────────
  function updatePanel(event, absolute) {
    const text = descriptions[event.phase] || [event.phase, ''];
    const tag = KIND_TAGS[event.kind];
    const tagNode = $('kind-tag');
    tagNode.textContent = tag ? tag[0] : '';
    tagNode.style.setProperty('--tag', tag ? tag[1] : '#cbd5e1');
    tagNode.hidden = !tag;
    $('phase').textContent = text[0];
    $('explanation').textContent = text[1] + (event.kind === 'evaluate' ? ' 채택 아님(평가 단계).' : '');
    $('kind-meaning').textContent = event.kind ? '공통 단계 ' + event.kind + ' · ' + (KIND_MEANINGS[event.kind] || '') : '';
    $('progress').textContent = (index + 1) + ' / ' + timeline.length + ' 장면 · 전체 기록 ' + (absolute + 1) + '번';
    $('decision').textContent = event.decision_reason || (event.decision ? event.decision.reason : '') || '';

    $('counts').textContent = event.iteration
      ? '확장 ' + event.iteration + '회 · 생성 ' + event.generated + '개 · 유지 ' + event.kept + '개 · 연결 대기 ' + event.finished + '개'
      : event.popped ? '큐에서 꺼냄 ' + event.popped + '회 · 대기 지점 ' + event.frontier.length + '개' : '';
    if (event.examined) $('counts').textContent = '검토 ' + event.examined + '회 · 이웃 방식 ' + event.neighborhood;
    if (event.shake_level) $('counts').textContent = '교란 레벨 ' + event.shake_level;
    if (event.accepted !== undefined) $('counts').textContent = event.accepted ? '채택' : '기각 / 기존 경로 유지';

    const values = $('stage-values');
    values.replaceChildren();
    const add = t => {
      const p = document.createElement('p');
      p.textContent = t;
      values.append(p);
    };
    const before = event.before_metrics, after = event.stage_metrics;
    if (after) {
      add(before ? (event.phase === 'winner' ? '이전 전체 최선 → 새 전체 최선'
          : event.kind === 'evaluate' ? '기존 경로 → 검토 후보' : '변경 전 → 이 단계 결과')
        : after.complete ? '이 장면의 완성 경로' : '탐색 중인 부분 경로 · 최종 결과 아님');
      add('거리: ' + (before ? km(before.distance_m) + ' → ' : '') + km(after.distance_m));
      if (after.target_error_m != null) {
        add('목표 오차: ' + (before?.target_error_m != null ? before.target_error_m.toFixed(1) + ' m → ' : '')
          + after.target_error_m.toFixed(1) + ' m');
      }
      add('재통행: ' + (before ? pct(before.repeated_edge_ratio) + ' → ' : '') + pct(after.repeated_edge_ratio));
      if (event.changed === false) add('개선 과정 전후에 경로 변화가 없습니다.');
    } else {
      add('도로 경로로 연결하기 전이므로 거리·재통행 수치를 표시하지 않습니다.');
    }
    const v = event.values;
    if (v && v.removed_nodes != null) add('정리로 줄어든 노드 ' + v.removed_nodes + '개');
    if (v && v.connection) add('연결 종류: ' + v.connection);
    if (v && v.f_m != null) {
      add('f = g + h: ' + meters(v.f_m) + ' = 지금까지 ' + meters(v.g_m) + ' + 남은 예상 ' + meters(v.h_m));
      add('휴리스틱: ' + (v.h_kind === 'alt' ? 'ALT 삼각부등식 하한' : 'Haversine 직선거리')
        + (v.best_landmark != null ? ' · 하한이 가장 큰 랜드마크 ' + v.best_landmark : ''));
      if (v.stale) add('이 항목은 이미 더 나은 경로로 확장한 노드라 건너뜁니다.');
      if (v.frontier_top && v.frontier_top.length) {
        add('다음 대기 후보(f 오름차순): ' + v.frontier_top.map(t => t.node + ' f ' + meters(t.f_m)).join(' · '));
      }
      if (v.expanded && v.expanded.length) {
        add('이웃 처리 ' + v.expanded.length + '개: ' + v.expanded.map(e => e.node + ' '
          + (e.result === 'skipped' ? '건너뜀' : '큐에 넣음') + '(' + (EXPANDED_REASONS[e.reason] || e.reason) + ')').join(' · '));
      }
    }
    if (v && v.popped != null) add('큐에서 꺼낸 횟수 ' + v.popped + '회 · 큐에 넣은 횟수 ' + v.pushed + '회');
    if (event.waypoint_changes) {
      const c = event.waypoint_changes;
      add('경유지: 제거 ' + c.removed.length + '개 · 추가 ' + c.added.length + '개'
        + (!c.removed.length && !c.added.length && c.order_changed ? ' · 순서 변경' : ''));
    }
    if (event.delta !== undefined) {
      add('ALNS 내부 평가값 변화 ' + event.delta.toFixed(3) + ' · 온도 ' + event.temperature.toFixed(3) + ' (도로 거리 변화와 다름)');
    }
    if (event.internal_before) {
      add('ALNS 내부 구간 거리 합: ' + km(event.internal_before.distance_m) + ' → ' + km(event.internal_after.distance_m));
      add('내부 목표 오차: ' + event.internal_before.error_m.toFixed(1) + ' m → '
        + event.internal_after.error_m.toFixed(1) + ' m · 도로 재연결·정리 전 평가');
    }
    if (event.phase === 'alns_result' && event.objective_after) {
      add('최종 반영 판단에 쓴 후보:');
      add('목표 오차 ' + event.objective_before.distance_error_m.toFixed(1) + ' m → ' + event.objective_after.distance_error_m.toFixed(1) + ' m');
      add('재통행 ' + pct(event.objective_before.repeated_edge_ratio) + ' → ' + pct(event.objective_after.repeated_edge_ratio));
      add(event.accepted ? '이 후보를 반영했습니다.' : '이 후보는 기각했으며 위 지도와 경로 수치는 유지된 결과입니다.');
    }
    const skipped = index ? timeline[index] - timeline[index - 1] - 1 : 0;
    $('scene-note').textContent = $('playback-mode').value === 'key'
      ? (skipped ? '앞선 반복 기록 ' + skipped + '개 생략. ' : '') + '변화·판단 중심의 대표 장면입니다. 나머지는 전체 기록에서 볼 수 있습니다.'
      : '기록된 모든 장면입니다. 지역 개선 후보 검토는 5개마다 표본 기록하며 실제 개선은 모두 기록합니다.';
    $('step').value = index;
    $('prev').disabled = index === 0;
    $('next').disabled = index === timeline.length - 1;
    $('replay').hidden = event.kind !== 'final';
  }

  // ── 장면 이동 ────────────────────────────────────────────
  function goto(next, animate = true) {
    cancelPathAnimation();
    index = Math.max(0, Math.min(timeline.length - 1, next));
    const event = currentEvent();
    if (event.kind === 'final') {
      // 최종 경로 범위로 옮긴 뒤 대표 후보를 출발점부터 그린다.
      applyCamera(event, animate, () => { startPathAnimation(); });
      return;
    }
    applyCamera(event, animate);
  }

  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
    $('play').textContent = '재생';
  }

  function setTimeline() {
    timeline = $('playback-mode').value === 'key' ? result.keyframes : result.trace.map((_, i) => i);
    $('step').max = timeline.length - 1;
    $('story-summary').textContent = timeline.length + '개 장면 / 전체 ' + result.trace.length + '개 기록';
  }

  function selectResult(mode) {
    stop();
    cancelPathAnimation();
    const found = data.results.find(r => r.mode === mode);
    if (!found) return;
    result = found;
    index = 0;
    camera = {...result.bounds};
    cameraMode = 'auto';
    $('camera-note').classList.remove('on');
    $('algorithm').value = mode;
    // 같은 결과를 가리키는 요청 문장이 여럿이라(예: "그냥 3km"와 "3km 순환") 이미 그 결과를
    // 가리키고 있으면 사용자가 고른 문장을 그대로 둔다.
    let chosen = data.cases[Number($('scenario').value)];
    if (!chosen || chosen.result !== mode) {
      const caseIndex = data.cases.findIndex(c => c.result === mode);
      chosen = caseIndex >= 0 ? data.cases[caseIndex] : null;
      if (caseIndex >= 0) $('scenario').value = String(caseIndex);
    }
    setTimeline();
    comparison();
    renderConditions();
    $('landmark-view').hidden = !(result.landmarks || []).length;
    $('intent').textContent = chosen && chosen.verification
      ? '이 요청은 기존 챗봇 규칙에 따라 순환 기록을 함께 보여줍니다. 실제 챗봇 응답 검증은 포함하지 않습니다.'
      : '도착점: ' + (result.start.node === result.end.node ? '출발점으로 복귀' : '경복궁역 3번 출입구')
        + ' · ' + result.engine + ' · ' + result.settings;
    const m = result.metrics[0];
    $('distance').textContent = m ? (m.distance_m / 1000).toFixed(3) + ' km' : '경로 없음';
    $('target').textContent = result.target_m
      ? '목표 ' + (result.target_m / 1000).toFixed(3) + ' km · 허용 오차 ±' + Math.round(result.tolerance_ratio * 100) + '%'
      : 'Dijkstra 거리와 대조한 최단 경로';
    $('quality').className = '';
    if (!result.route_valid) {
      $('quality').textContent = '경로 연결 또는 출발·도착 검증 실패';
      $('quality').className = 'warning';
    } else if (m?.target_within_tolerance === false) {
      $('quality').textContent = '목표 범위 벗어남 · 오차 ' + Math.round(m.target_error_m) + 'm';
      $('quality').className = 'warning';
    } else {
      $('quality').textContent = m.target_error_m === null ? '연결·출발·도착 검증 통과'
        : '목표 범위 안 · 오차 ' + Math.round(m.target_error_m) + 'm';
    }
    goto(0, false);
  }

  function play() {
    if (timer !== null) {
      stop();
      return;
    }
    if (index === timeline.length - 1) index = 0;
    $('play').textContent = '일시정지';
    timer = setInterval(() => {
      goto(index + 1);
      if (index === timeline.length - 1) stop();
    }, Number($('speed').value));
  }

  // ── 조작 ─────────────────────────────────────────────────
  function zoom(factor) {
    setManual(true);
    camera.radius = Math.max(30, Math.min(result.bounds.radius * 2, camera.radius * factor));
    draw();
  }

  $('algorithm').onchange = () => selectResult($('algorithm').value);
  $('scenario').onchange = () => {
    const chosen = data.cases[Number($('scenario').value)];
    if (chosen) selectResult(chosen.result);
  };
  $('playback-mode').onchange = () => {
    stop();
    const raw = timeline[index];
    setTimeline();
    const next = timeline.findIndex(i => i >= raw);
    goto(next < 0 ? timeline.length - 1 : next, false);
  };
  $('prev').onclick = () => { stop(); goto(index - 1); };
  $('next').onclick = () => { stop(); goto(index + 1); };
  $('final').onclick = () => { stop(); goto(timeline.length - 1); };
  $('reset').onclick = () => { stop(); goto(0); };
  $('step').oninput = () => { stop(); goto(Number($('step').value)); };
  $('play').onclick = play;
  $('speed').onchange = () => { if (timer !== null) { stop(); play(); } };
  $('replay').onclick = () => { if (currentEvent().kind === 'final') startPathAnimation(); };
  $('camera-auto').onclick = () => setManual(false);
  $('zoom-in').onclick = () => zoom(.7);
  $('zoom-out').onclick = () => zoom(1 / .7);
  // 전체보기는 범위만 되돌리고 자동/수동 상태는 바꾸지 않는다.
  $('fit').onclick = () => { camera = {...result.bounds}; draw(); };
  $('landmark-view').onclick = () => {
    const coords = [[result.bounds.cx - result.bounds.radius, result.bounds.cy - result.bounds.radius],
                    [result.bounds.cx + result.bounds.radius, result.bounds.cy + result.bounds.radius],
                    ...(result.landmarks || [])];
    const box = boundsOf(coords);
    setManual(true);
    camera = {cx: (box.minX + box.maxX) / 2, cy: (box.minY + box.maxY) / 2,
              radius: Math.max(box.maxX - box.minX, box.maxY - box.minY) / 2 * 1.1};
    draw();
  };

  canvas.addEventListener('wheel', e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15); }, {passive: false});
  const pointers = new Map();
  canvas.onpointerdown = e => {
    pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
    canvas.setPointerCapture(e.pointerId);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = {distance: Math.hypot(a.x - b.x, a.y - b.y), radius: camera.radius};
      drag = null;
    } else {
      drag = {x: e.clientX, y: e.clientY};
    }
  };
  canvas.onpointermove = e => {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (distance > 0 && pinch.distance > 0) {
        setManual(true);
        camera.radius = Math.max(30, Math.min(result.bounds.radius * 2, pinch.radius * pinch.distance / distance));
        draw();
      }
      return;
    }
    if (drag) {
      setManual(true);
      camera.cx -= (e.clientX - drag.x) / lastScale;
      camera.cy += (e.clientY - drag.y) / lastScale;
      drag = {x: e.clientX, y: e.clientY};
      draw();
    }
  };
  canvas.onpointerup = canvas.onpointercancel = e => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) drag = null;
  };
  mini.onclick = e => {
    const box = mini.getBoundingClientRect();
    const scale = (Math.min(box.width, box.height) - 10) / (result.bounds.radius * 2);
    setManual(true);
    camera.cx = result.bounds.cx + (e.clientX - box.left - box.width / 2) / scale;
    camera.cy = result.bounds.cy - (e.clientY - box.top - box.height / 2) / scale;
    draw();
  };
  new ResizeObserver(() => draw()).observe(canvas);

  // ── 시작 ─────────────────────────────────────────────────
  buildPickers();
  const first = data.results.find(r => r.mode === 'circular') || data.results[0];
  selectResult(first.mode);

  // ── 자가 점검(?selftest=1) ───────────────────────────────
  // 모든 결과 × 모든 장면을 실제로 그려 보고 결과를 <pre id="selftest-result">에 남긴다.
  async function selftest() {
    const failures = [];
    let checks = 0;
    const check = (ok, message) => {
      checks++;
      if (!ok) failures.push(message);
    };
    check($('algorithm').querySelectorAll('option:disabled').length
      === (data.catalog || []).filter(entry => !entry.available).length,
      '선택 화면의 disabled 항목 수가 catalog의 available=false 수와 다릅니다.');
    let landmarkLabels = 0;
    const hasLandmarks = data.results.some(item => (item.landmarks || []).length);
    for (const item of data.results) {
      selectResult(item.mode);
      $('playback-mode').value = 'all';
      setTimeline();
      for (let step = 0; step < timeline.length; step++) {
        cameraMode = 'auto';
        goto(step, false);
        const event = currentEvent();
        check(camera.radius >= MIN_RADIUS - 1e-6 && camera.radius <= result.bounds.radius + 1e-6,
          item.mode + ' ' + step + '번 장면의 자동 확대 반지름이 범위 밖입니다: ' + camera.radius);
        if (event.kind === 'reject' && keptBeside(event, timeline[step])) {
          check(stats.keptOverlay && stats.drawnPaths > event.paths.length,
            item.mode + ' ' + step + '번 기각 장면에 유지 후보가 함께 그려지지 않았습니다.');
        }
        check(stats.minimap && stats.minimap.cx === camera.cx && stats.minimap.radius === camera.radius,
          item.mode + ' ' + step + '번 장면의 미니맵 사각형이 카메라와 다릅니다.');
        // 다듬기 (a): A* 장면이 현재 지점에 너무 붙어 주변을 못 보는 일이 없어야 한다.
        if ((event.values || {}).f_m != null) {
          check(camera.radius >= MIN_RADIUS - 1e-6,
            item.mode + ' ' + step + '번 A* 장면의 자동 확대 반지름이 ' + MIN_RADIUS
            + 'm보다 좁습니다: ' + camera.radius);
        }
        // 다듬기 (b): 랜드마크 방향 점선이 화면을 벗어나면 방향·거리 라벨이 있어야 한다.
        if (stats.landmarkRayOffscreen) {
          check(stats.landmarkLabel !== null || stats.landmarkLabelSkipped,
            item.mode + ' ' + step + '번 장면: 화면 밖 랜드마크 방향에 라벨이 없습니다.');
          if (stats.landmarkLabel) landmarkLabels++;
        }
        if (event.kind === 'final') {
          const drawing = startPathAnimation();
          finishPathAnimation();
          await drawing;
          check(pathAnim && pathAnim.done && pathAnim.progress === 1,
            item.mode + '의 최종 경로 애니메이션이 완료 상태에 도달하지 않았습니다.');
          check(stats.drawnPaths >= event.paths.length,
            item.mode + '의 최종 장면에서 반환 경로가 그려지지 않았습니다.');
        }
      }
    }
    if (hasLandmarks) {
      check(landmarkLabels > 0,
        'ALT 결과가 있는데 랜드마크 방향 라벨이 한 번도 그려지지 않았습니다.');
    }
    return {checks, failures, results: data.results.length, landmarkLabels};
  }

  if (SELFTEST) {
    selftest().then(report => {
      $('selftest-result').textContent = JSON.stringify(
        {passed: report.checks - report.failures.length, checks: report.checks,
         results: report.results, landmarkLabels: report.landmarkLabels,
         failures: report.failures}, null, 2);
    }).catch(error => {
      $('selftest-result').textContent = JSON.stringify(
        {passed: 0, checks: 0, failures: ['예외: ' + (error && error.message ? error.message : String(error))]}, null, 2);
    });
  }
})();
