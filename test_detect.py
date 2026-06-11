# video_editor.html의 자막 감지 로직을 그대로 재현한 오프라인 테스트
# 사용: python test_detect.py [영상경로]
import os
import sys

import cv2
import numpy as np

VIDEO = sys.argv[1] if len(sys.argv) > 1 else "3단빨래.mp4"
OUT = "test_crops"

# === HTML과 동일한 상수 ===
SAMPLE_STEP = 0.35
BOTTOM_RATIO = 0.30
MIN_DUR = 0.25
SCALE_W = 960
BRIGHT_WHITE = 195
DARK_ABS = 520          # 윤곽 절대 임계 (r+g+b)
DARK_REL = 100          # 글자보다 이만큼 어두우면 윤곽 (흰 옷 위 연한 자막박스 대응)
NEIGHBOR_OFF = 4
PRESENT_MIN = 80
PRESENT_RATIO = 0.0015
SIG_GW, SIG_GH = 96, 12
SIG_CELL_TH = 0.12
SIG_IOU = 0.55
ROW_EXPAND = 0.12
COL_TRIM = 0.02
PEAK_MIN = 6


TOPHAT_K = 9            # 탑햇 커널 (이보다 가는 밝은 획만 남는다)
TOPHAT_TH = 55          # 획-배경 밝기 차 임계
BRIGHT_MIN = 160        # 글자 최소 밝기


def analyze_band(band_bgr):
    # 탑햇: 넓게 밝은 영역(하늘·흰옷)은 지워지고 가는 밝은 획(글자)만 남는다
    gray = band_bgr.max(axis=2)  # 흰색·노란색 글자 모두 밝게 잡힘
    opened = cv2.morphologyEx(gray, cv2.MORPH_OPEN,
                              np.ones((TOPHAT_K, TOPHAT_K), np.uint8))
    tophat = gray.astype(np.int32) - opened.astype(np.int32)
    mask = (tophat > TOPHAT_TH) & (gray > BRIGHT_MIN)
    # 가로/세로로 길게 이어진 선(창틀, 자막박스 테두리 등) 제거
    # 41px: 글자 한 획(一 같은 가로획 ~25px)보다 길고 창틀·테두리보다 짧다
    m8 = mask.astype(np.uint8)
    horiz = cv2.morphologyEx(m8, cv2.MORPH_OPEN, np.ones((1, 41), np.uint8))
    vert = cv2.morphologyEx(m8, cv2.MORPH_OPEN, np.ones((41, 1), np.uint8))
    return (m8 & ~(horiz | vert)).astype(bool)


def signature(mask):
    h, w = mask.shape
    m = mask.astype(np.float32)
    sig = cv2.resize(m, (SIG_GW, SIG_GH), interpolation=cv2.INTER_AREA)
    return sig > SIG_CELL_TH


def same_sig(a, b):
    if a is None or b is None:
        return False
    uni = np.logical_or(a, b).sum()
    if uni == 0:
        return True
    return np.logical_and(a, b).sum() / uni > SIG_IOU


TEXT_WIN = 36           # 글줄 탐색 창 높이(px)
DENSITY_MIN = 0.08      # bbox 안 글자 픽셀 밀도 하한 (옷걸이 등 성긴 노이즈 제거)


def bbox_of(mask):
    h, w = mask.shape
    row_c = mask.sum(axis=1).astype(np.float64)
    if row_c.sum() == 0:
        return None
    # 픽셀이 가장 밀집된 36px 글줄 띠를 찾는다 (테두리 한 줄짜리 피크에 낚이지 않게)
    win = min(TEXT_WIN, h)
    roll = np.convolve(row_c, np.ones(win), mode="valid")
    wy = int(np.argmax(roll))
    band = row_c[wy:wy + win]
    peak = band.max()
    if peak < PEAK_MIN:
        return None
    rows = np.where(band >= max(2.0, peak * ROW_EXPAND))[0]
    y1, y2 = wy + int(rows[0]), wy + int(rows[-1])
    col_c = mask[y1:y2 + 1].sum(axis=0)
    sub = col_c.sum()
    if sub == 0:
        return None
    trim = sub * COL_TRIM
    cum = np.cumsum(col_c)
    x1 = int(np.searchsorted(cum, trim, side="right"))
    cum_r = np.cumsum(col_c[::-1])
    x2 = w - 1 - int(np.searchsorted(cum_r, trim, side="right"))
    if x2 <= x1 or y2 <= y1:
        return None
    # 자막 글줄 사니티: 줄 높이 10~70px, 폭 50px 이상, 밀도 8% 이상
    bw, bh = x2 - x1 + 1, y2 - y1 + 1
    if not (10 <= bh <= 70) or bw < 50:
        return None
    density = mask[y1:y2 + 1, x1:x2 + 1].sum() / (bw * bh)
    if density < DENSITY_MIN:
        return None
    return (x1, y1, x2, y2)


def scan(cap, dur, sw, sh_, row0, row1, pad_crop=14):
    """row0~row1 행 범위에서 자막 구간 스캔 (bbox는 row0 기준 좌표)"""
    segs = []
    cur = None
    cur_sig = None

    def close():
        nonlocal cur, cur_sig
        if cur and (cur["t1"] - cur["t0"]) >= MIN_DUR:
            segs.append(cur)
        cur = None
        cur_sig = None

    t = 0.05
    while t < dur:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.resize(frame, (sw, sh_))
        band = frame[row0:row1]
        mask = analyze_band(band)
        count = int(mask.sum())
        present = count > max(PRESENT_MIN, int(mask.size * PRESENT_RATIO))
        if present:
            sig = signature(mask)
            if cur is not None and same_sig(cur_sig, sig):
                cur["t1"] = t
            else:
                close()
                bb = bbox_of(mask)
                if bb is not None:
                    x1, y1, x2, y2 = bb
                    p = pad_crop
                    cx1, cy1 = max(0, x1 - p), max(0, row0 + y1 - p)
                    cx2 = min(sw, x2 + p)
                    cy2 = min(sh_, row0 + y2 + p)
                    cur = {"t0": t, "t1": t, "bb": bb,
                           "crop": frame[cy1:cy2, cx1:cx2].copy()}
                    cur_sig = sig
        else:
            close()
        t += SAMPLE_STEP
    close()
    return segs


def main():
    cap = cv2.VideoCapture(VIDEO)
    if not cap.isOpened():
        print("영상 열기 실패:", VIDEO)
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dur = total_f / fps
    scale = min(1.0, SCALE_W / vw)
    sw, sh_ = round(vw * scale), round(vh * scale)
    band_y = round(sh_ * (1 - BOTTOM_RATIO))
    print(f"영상 {vw}x{vh} {fps:.2f}fps {dur:.1f}s → 분석 {sw}x{sh_}, 자막띠 y>={band_y}")

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))

    # 1패스: 하단 전체에서 자막의 지배적 세로 위치 찾기
    pass1 = scan(cap, dur, sw, sh_, band_y, sh_)
    if not pass1:
        print("자막을 찾지 못했습니다.")
        return
    ycs = []
    for s in pass1:
        yc = band_y + (s["bb"][1] + s["bb"][3]) / 2
        ycs += [yc] * max(1, round((s["t1"] - s["t0"]) / SAMPLE_STEP))
    yc_med = float(np.median(ycs))
    print(f"1패스: {len(pass1)}개 구간, 자막 줄 위치 y={yc_med:.0f}")

    # 2패스: 자막 줄 주변만 다시 스캔 (다른 영역 노이즈 차단)
    strip0 = max(0, int(yc_med - 45))
    strip1 = min(sh_, int(yc_med + 45))
    segs = scan(cap, dur, sw, sh_, strip0, strip1)
    print(f"2패스: y={strip0}~{strip1} 띠에서 {len(segs)}개 구간")

    print(f"\n=== 감지된 구간: {len(segs)}개 ===")
    for i, s in enumerate(segs):
        s["t1"] += SAMPLE_STEP * 0.6
        x1, y1, x2, y2 = s["bb"]
        fn = f"{OUT}/seg{i:02d}_{s['t0']:.1f}-{s['t1']:.1f}.png"
        cv2.imwrite(fn, s["crop"])
        print(f"  #{i:02d} {s['t0']:5.1f}~{s['t1']:5.1f}s  "
              f"bbox=({x1},{y1})-({x2},{y2}) w={x2-x1} h={y2-y1}  → {fn}")

    # 자막이 안 잡힌 시간대(공백) 표시
    print("\n=== 커버되지 않은 시간대 (1초 이상) ===")
    prev_end = 0.0
    for s in segs:
        if s["t0"] - prev_end > 1.0:
            print(f"  {prev_end:.1f} ~ {s['t0']:.1f}s ({s['t0']-prev_end:.1f}초 공백)")
        prev_end = max(prev_end, s["t1"])
    if dur - prev_end > 1.0:
        print(f"  {prev_end:.1f} ~ {dur:.1f}s ({dur-prev_end:.1f}초 공백)")


if __name__ == "__main__":
    main()
