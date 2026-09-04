#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
my-gptimage-habits — 用 gpt-image-2 直接出图（复刻个人创作习惯的默认参数）。

用法：
  python gimg.py --prompt "…" [--images a.png b.png] [--size auto] [--quality auto]
                 [--n 1] [--transparent] [--out-dir out] [--name 资产名]
                 [--timeout 1000] [--dry-run]

配置命令（首次使用）：
  python gimg.py --show-config
  python gimg.py --set-key <你的key> [--set-base-url <url>]

接口协议（2026-09-04 在 https://ai-pixel.online 实测核实）：
  - 端点：无参考图 POST {base}/v1/images/generations（JSON）；
    有参考图 POST {base}/v1/images/edits（multipart，image[] 字段，顺序=@图1/@图2…）
  - prompt 中的 @图N（含零宽标记）自动转换为 [image N]
  - 【重要】该中转站忽略 size 参数（实测发 720x1280 仍返回 1672x941）：
    比例靠 prompt 写“（16：9）/（9：16）”等，--size 传 auto 即可（传了也无害）
  - 【重要】透明底规则（2026-09-04 用户实测 + 本脚本验证）：
    * 文生图（无参考图）：prompt 写“透明底”→ 直接返回带 alpha 的真透明 PNG，
      且排版设计质量比绿底版更好 —— 这是首选
    * 图生图（有参考图）：prompt 写“透明底”**不生效** → 改用绿底链路：
      prompt 写“背景设置为方便抠图的纯绿色背景”+ `--unkey`（出绿底图后本地抠键色，
      输出真透明 PNG；已带 alpha 的图自动跳过抠色）
  - 单请求 n>1 行为不稳定（中转站按账号随机分配，有时支持有时拒绝，用户实测）：
    脚本被拒时最多 3 轮（每轮 3 次重试）再退化为串行 n=1，串行前等 20s 让网关恢复
  - 接口不支持 background: transparent 参数（HTTP 400，勿发）
  - --transparent = 兜底模式（平时不用）：prompt 追加 [背景指令] 块（绿 #00FF00 /
    主体含绿色则洋红 #FF00FF 纯色底）+ 本地键色抠除（纯标准库实现）。
    仅在文生图“透明底”没生效、返回图无 alpha 时使用
  - 出图后若 prompt 含“透明底/透明背景”但结果无 alpha 通道，脚本会明确警告
  - 绿幕抠图（你的常用习惯）不加参数：prompt 写“背景设置为方便抠图的纯绿色背景”，
    交付绿底 PNG 给剪辑软件做色度键

参数约定（来自个人习惯规则，详见 references/parameters.md）：
  - model 固定 gpt-image-2；output_format 固定 png；moderation 固定 auto
  - size 默认 auto（比例写进 prompt）；quality 默认 auto
  - n 默认 1；探索设计用 2（接口不支持单请求 n>1，脚本自动串行）
  - 一次只发一个请求（账号有并发上限）

key 读取优先级：环境变量 GPTIMAGE_API_KEY
            > ~/.gptimage/config.json（本技能）
            > ~/.gptimage-ppt/config.json（与 gptimage-ppt 共享）
base_url 优先级：环境变量 GPTIMAGE_BASE_URL > 配置 > https://ai-pixel.online
本脚本不内置任何 key，避免泄露。
"""

import argparse
import base64
import getpass
import io
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib

DEFAULT_BASE_URL = "https://ai-pixel.online"
DEFAULT_MODEL = "gpt-image-2"
CONFIG_PATHS = [
    os.path.expanduser(os.path.join("~", ".gptimage", "config.json")),
    os.path.expanduser(os.path.join("~", ".gptimage-ppt", "config.json")),
]

GREEN_KEY = (0, 255, 0)
MAGENTA_KEY = (255, 0, 255)

# 与平台 src/lib/transparentImage.ts 的 TRANSPARENT_PROMPT_TEMPLATE 完全一致
TRANSPARENT_PROMPT_TEMPLATE = "\n".join([
    "[背景指令]",
    "背景色选择规则：如果主体包含绿色系（绿、青绿、黄绿、草绿等）颜色，使用纯洋红色(#FF00FF)背景；否则一律使用纯绿色(#00FF00)背景。",
    "背景要求：整张画布仅由所选纯色填充，无任何渐变、纹理、阴影、光照变化、地面或环境元素。",
    "主体要求：单主体、完整呈现、轮廓清晰锐利。主体与背景之间保持干净的边缘分离，不要有颜色溢出或混合。",
    "禁止：主体本身、描边、光晕、投影或反射中不能出现所选背景色。",
])

MENTION_RE = re.compile("\u2063@图(\d+)\u2064|@图(\d+)")


# ---------------- 配置 ----------------

def slug(text, maxlen=24):
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", text or "").strip("-")
    return text[:maxlen] or "image"


def mask(key):
    if not key:
        return "（未设置）"
    return "%s…%s" % (key[:6], key[-4:])


def load_first_config():
    for path in CONFIG_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                return cfg, path
        except (OSError, ValueError):
            continue
    return {}, None


def save_config(cfg):
    path = CONFIG_PATHS[0]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def resolve_config():
    cfg, cfg_path = load_first_config()
    key = os.environ.get("GPTIMAGE_API_KEY") or cfg.get("api_key") or ""
    base_url = os.environ.get("GPTIMAGE_BASE_URL") or cfg.get("base_url") or DEFAULT_BASE_URL
    src = ("环境变量" if os.environ.get("GPTIMAGE_API_KEY")
           else ("配置文件 " + cfg_path if cfg_path and cfg.get("api_key") else "无"))
    return key, base_url, src


# ---------------- 提示词处理 ----------------

def convert_mentions(prompt):
    def sub(m):
        n = m.group(1) or m.group(2)
        return "[image %s]" % n
    out = MENTION_RE.sub(sub, prompt)
    return out.replace("\u2063", "").replace("\u2064", "")


def build_transparent_prompt(prompt):
    return "%s\n\n%s" % (prompt.strip(), TRANSPARENT_PROMPT_TEMPLATE)


# ---------------- PNG 编解码（纯标准库） ----------------

def _png_decode(raw):
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("不是 PNG 文件")
    pos = 8
    width = height = bitdepth = colortype = None
    idat = b""
    plte = None
    trns = None
    while pos < len(raw):
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        ctype = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bitdepth, colortype = struct.unpack(">IIBB", data[:10])
        elif ctype == b"PLTE":
            plte = data
        elif ctype == b"tRNS":
            trns = data
        elif ctype == b"IDAT":
            idat += data
        elif ctype == b"IEND":
            break
    if width is None:
        raise ValueError("PNG 缺少 IHDR")
    if bitdepth != 8:
        raise ValueError("仅支持 8bit PNG（当前 %sbit），请安装 Pillow 后重试" % bitdepth)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colortype)
    if channels is None:
        raise ValueError("不支持的 PNG 颜色类型 %s" % colortype)
    px = zlib.decompress(idat)
    stride = width * channels
    out = bytearray()
    prev = bytearray(stride)
    off = 0
    for _ in range(height):
        f = px[off]
        off += 1
        line = bytearray(px[off:off + stride])
        off += stride
        if f == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                upleft = prev[i - channels] if i >= channels else 0
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                pr = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upleft)
                line[i] = (line[i] + pr) & 0xFF
        if colortype == 3:
            for i in range(width):
                idx = line[i] * 3
                r, g, b = plte[idx], plte[idx + 1], plte[idx + 2]
                a = trns[idx] if trns and idx < len(trns) else 255
                out += bytes((r, g, b, a))
        elif colortype == 2:
            for i in range(0, stride, 3):
                out += line[i:i + 3] + b"\xff"
        elif colortype == 0:
            for i in range(width):
                out += bytes((line[i],) * 3 + (255,))
        elif colortype == 4:
            for i in range(0, stride, 2):
                out += bytes((line[i],) * 3 + (line[i + 1],))
        else:
            out += line
        prev = line
    return width, height, bytes(out)


def _png_encode(width, height, rgba):
    def chunk(ctype, data):
        c = struct.pack(">I", len(data)) + ctype + data
        return c + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)

    raw = io.BytesIO()
    for y in range(height):
        raw.write(b"\x00")
        raw.write(rgba[y * width * 4:(y + 1) * width * 4])
    head = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
            + chunk(b"IDAT", zlib.compress(raw.getvalue(), 9))
            + chunk(b"IEND", b""))


def _png_has_alpha(raw):
    """仅读 IHDR 判断 PNG 是否带 alpha 通道（colortype 4/6 或 3+tRNS）。"""
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    pos = 8
    colortype = None
    has_trns = False
    while pos < len(raw):
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        ctype = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            colortype = data[9]
        elif ctype == b"tRNS":
            has_trns = True
        elif ctype == b"IEND":
            break
    if colortype in (4, 6):
        return True
    if colortype == 3 and has_trns:
        return True
    return False


# ---------------- 键色抠除（与平台 transparentImage.ts 同算法） ----------------

def _clamp01(v):
    return max(0.0, min(1.0, v))


def _key_channel_mix(r, g, b, key):
    if key[1] == 255:  # 绿键
        return _clamp01((g - min(r, b)) / 255.0)
    return _clamp01((min(r, b) - g * 0.65) / 255.0)  # 洋红键


def _confidence(r, g, b, key):
    d = ((r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2) ** 0.5
    return _clamp01((150 - d) / 150.0)


def _detect_key(borders):
    green_score = magenta_score = 0
    for r, g, b in borders:
        if ((r - 0) ** 2 + (g - 255) ** 2 + (b - 0) ** 2) ** 0.5 < 100:
            green_score += 1
        if ((r - 255) ** 2 + (g - 0) ** 2 + (b - 255) ** 2) ** 0.5 < 100:
            magenta_score += 1
    return MAGENTA_KEY if magenta_score > green_score else GREEN_KEY


def _unkey(width, height, rgba, key=None):
    n = width * height
    px = [tuple(rgba[i * 4:i * 4 + 3]) for i in range(n)]
    if key is None:
        borders = list(px[:width]) + list(px[n - width:])
        for y in range(1, height - 1):
            borders.append(px[y * width])
            borders.append(px[y * width + width - 1])
        key = _detect_key(borders)
    conf = [_confidence(r, g, b, key) for r, g, b in px]

    # 1) 从边界连通泛洪（置信度 >= 0.18）
    mask = bytearray(n)
    visited = bytearray(n)
    queue = []
    head = 0

    def enqueue(i):
        if visited[i]:
            return
        visited[i] = 1
        if conf[i] < 0.18:
            return
        mask[i] = 1
        queue.append(i)

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(1, height - 1):
        enqueue(y * width)
        enqueue(y * width + width - 1)
    while head < len(queue):
        i = queue[head]
        head += 1
        x = i % width
        y = i // width
        if x > 0:
            enqueue(i - 1)
        if x < width - 1:
            enqueue(i + 1)
        if y > 0:
            enqueue(i - width)
        if y < height - 1:
            enqueue(i + width)

    # 2) 内部键色孤岛
    queue2 = []
    for seed in range(n):
        if mask[seed] or visited[seed] or conf[seed] < 0.68:
            continue
        visited[seed] = 1
        queue2.append(seed)
        h2 = 0
        comp = []
        conf_sum = 0.0
        strict = strong = 0
        while h2 < len(queue2):
            i = queue2[h2]
            h2 += 1
            comp.append(i)
            c = conf[i]
            conf_sum += c
            if c >= 0.68:
                strict += 1
            if c >= 0.86:
                strong += 1
            x = i % width
            y = i // width
            for nb in (i - 1, i + 1, i - width, i + width):
                if nb < 0 or nb >= n:
                    continue
                if nb == i - 1 and x == 0 or nb == i + 1 and x == width - 1:
                    continue
                if mask[nb] or visited[nb] or conf[nb] < 0.24:
                    continue
                visited[nb] = 1
                queue2.append(nb)
        length = len(comp)
        avg = conf_sum / length
        remove = (avg >= 0.42 or strict / length >= 0.18 or strong / length >= 0.05
                  or (length <= 3 and avg >= 0.34))
        if remove:
            for i in comp:
                mask[i] = 1
        del queue2[:]

    # 3) 到背景的距离（1..4）
    dist = bytearray(n)
    frontier = []
    for i in range(n):
        if mask[i]:
            continue
        x = i % width
        y = i // width
        touches = ((x > 0 and mask[i - 1]) or (x < width - 1 and mask[i + 1])
                   or (y > 0 and mask[i - width]) or (y < height - 1 and mask[i + width]))
        if touches:
            dist[i] = 1
            frontier.append(i)
    cur = 1
    while frontier and cur < 4:
        nxt = []
        for i in frontier:
            x = i % width
            y = i // width
            for nb in (i - 1, i + 1, i - width, i + width):
                if nb < 0 or nb >= n:
                    continue
                if nb == i - 1 and x == 0 or nb == i + 1 and x == width - 1:
                    continue
                if mask[nb] or dist[nb]:
                    continue
                dist[nb] = cur + 1
                nxt.append(nb)
        frontier = nxt
        cur += 1

    # 4) 写 alpha + 去溢色
    out = bytearray(n * 4)
    for i in range(n):
        r, g, b = px[i]
        c = conf[i]
        d = dist[i]
        if mask[i]:
            alpha = 0
        else:
            alpha = 255
            if d > 0:
                strength = {1: 1.0, 2: 0.75, 3: 0.45}.get(d, 0.25)
                dist_est = _clamp01(((c - 0.08) / 0.84) * strength)
                ch_est = _key_channel_mix(r, g, b, key) * strength
                transparency = _clamp01(max(dist_est, ch_est))
                if transparency > 0:
                    alpha = round(255 * (1 - transparency))
                alpha = max(alpha, 48 if d == 1 else (128 if d == 2 else 196))
            else:
                spill = _key_channel_mix(r, g, b, key)
                if c >= 0.46 and spill >= 0.45:
                    alpha = round(255 * (1 - spill * 0.75))
                    alpha = max(alpha, 96)
        if alpha == 0:
            rr, gg, bb = r, g, b
        else:
            if d <= 0:
                strength = 0.35 if c >= 0.46 else 0.0
            elif d == 1:
                strength = 0.55
            elif d == 2:
                strength = 0.32
            else:
                strength = 0.16
            spill_mix = _key_channel_mix(r, g, b, key) * strength
            bg_mix = _clamp01(max((255 - alpha) / 255.0, ((c - 0.1) / 0.9) * strength, spill_mix))
            if bg_mix <= 0:
                rr, gg, bb = r, g, b
            else:
                fg = max(0.08, 1 - bg_mix)

                def cb(v):
                    return max(0, min(255, round(v)))
                rr = cb((r - key[0] * bg_mix) / fg)
                gg = cb((g - key[1] * bg_mix) / fg)
                bb = cb((b - key[2] * bg_mix) / fg)
        out[i * 4:i * 4 + 4] = bytes((rr, gg, bb, alpha))
    return bytes(out), key


# ---------------- 请求 ----------------

def build_fields(prompt, size, quality, n):
    fields = {
        "model": DEFAULT_MODEL,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "output_format": "png",
        "moderation": "auto",
    }
    if n > 1:
        fields["n"] = str(n)
    return fields


def build_json_body(fields):
    body = dict(fields)
    if "n" in body:
        body["n"] = int(body["n"])
    return body


def build_multipart(fields, image_paths):
    boundary = "----gimg" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode("utf-8"))
    for i, p in enumerate(image_paths):
        ext = os.path.splitext(p)[1].lower().lstrip(".")
        if ext in ("jpg", "jpeg"):
            ext, ctype = "jpeg", "image/jpeg"
        elif ext == "webp":
            ctype = "image/webp"
        else:
            ext, ctype = "png", "image/png"
        with open(p, "rb") as f:
            data = f.read()
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"image[]\"; filename=\"input-%d.%s\"\r\n"
                   "Content-Type: %s\r\n\r\n" % (boundary, i + 1, ext, ctype)).encode("utf-8"))
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode("utf-8"))
    return buf.getvalue(), "multipart/form-data; boundary=" + boundary


def _post(url, key, data, headers, timeout):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_images(body):
    items = body.get("data") or []
    if not items:
        raise RuntimeError("响应里没有 data：" + str(body)[:400])
    out = []
    for it in items:
        b64 = it.get("b64_json")
        if b64:
            out.append(base64.b64decode(b64))
            continue
        url = it.get("url")
        if url:
            with urllib.request.urlopen(url, timeout=120) as r:
                out.append(r.read())
            continue
        raise RuntimeError("响应项既无 b64_json 也无 url：" + str(it)[:300])
    return out


def _do_request(url, key, data, content_type, timeout):
    last = "unknown error"
    for attempt in range(3):
        try:
            body = _post(url, key, data, {"Authorization": "Bearer " + key,
                                          "Content-Type": content_type}, timeout)
            return _extract_images(body), body
        except urllib.error.HTTPError as e:
            last = "HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:400])
            if "multipart" in last and "EOF" in last:
                # 中转站在批量 400 后对大文件上传有惩罚窗口（约 1~5 分钟），
                # 短重试无效，等 45s 让惩罚过期
                print("  网关大文件上传被截断（multipart EOF），等 45s 让惩罚窗口过期…")
                time.sleep(45)
            else:
                time.sleep(15 if e.code == 429 else min(2 ** attempt, 8))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("生成失败（已重试 3 次）：" + last)


def generate(prompt, image_paths, size, quality, n, transparent, base_url, key, timeout, unkey=False):
    api_prompt = convert_mentions(prompt)
    if transparent:
        api_prompt = build_transparent_prompt(api_prompt)
    n_total = max(1, n)
    url = base_url.rstrip("/") + ("/v1/images/edits" if image_paths else "/v1/images/generations")
    fields = build_fields(api_prompt, size, quality, n_total)

    if not image_paths:
        data = json.dumps(build_json_body(fields)).encode("utf-8")
        ct = "application/json"
    else:
        data, ct = build_multipart(fields, image_paths)

    pngs = None
    if n_total > 1:
        if image_paths:
            # 图生图（multipart 大文件）：实测多次 n>1 尝试会让网关后续大文件上传报
            # “multipart: NextPart: EOF”，所以直接串行 n=1，不浪费大文件上传。
            print("  n=%d：图生图直接串行 n=1（中转站 n>1 行为不稳，避免弄坏网关）" % n_total)
        else:
            # 文生图（JSON body 小）：先按单请求 n>1 尝试；中转站按账号随机分配，
            # n>1 是否支持可能因账号而异（用户实测：有时可以），被拒时多试几轮再串行。
            for round_ in range(3):
                try:
                    pngs, _ = _do_request(url, key, data, ct, timeout)
                    break
                except RuntimeError as e:
                    if "HTTP 4" not in str(e):
                        raise
                    if round_ < 2:
                        print("  n=%d 单请求被拒（%s），10s 后第 %d 轮重试（中转站可能换账号）…"
                              % (n_total, str(e)[:100], round_ + 2))
                        time.sleep(10)
                    else:
                        print("  n=%d 单请求 3 轮仍被拒，退化为串行 n=1" % n_total)
        if pngs is None:
            pngs = []
            single = dict(fields)
            single.pop("n", None)
            if not image_paths:
                sdata = json.dumps(build_json_body(single)).encode("utf-8")
            else:
                sdata = None
            for i in range(n_total):
                print("  串行第 %d/%d 张…" % (i + 1, n_total))
                if image_paths:
                    # 每次重建 multipart（新 boundary），规避网关在连续大文件上传后的残留状态
                    sdata, _ = build_multipart(single, image_paths)
                one, _ = _do_request(url, key, sdata, ct, timeout)
                pngs.extend(one)
    else:
        pngs, _ = _do_request(url, key, data, ct, timeout)

    if transparent or unkey:
        fixed = []
        for i, raw in enumerate(pngs):
            if _png_has_alpha(raw):
                # 已是真透明（文生图“透明底”直出），无需再抠
                print("  第%d张已带 alpha 通道，跳过抠键色" % (i + 1))
                fixed.append(raw)
                continue
            try:
                w, h, rgba = _png_decode(raw)
                rgba2, used = _unkey(w, h, rgba)
                fixed.append(_png_encode(w, h, rgba2))
                print("  透明后处理：第%d张 键色=%s" % (i + 1, "#%02X%02X%02X" % used))
            except ValueError as e:
                print("  透明后处理跳过（%s），交付原始图" % e)
                fixed.append(raw)
        pngs = fixed
    return pngs, api_prompt


# ---------------- CLI ----------------

def do_configure(a):
    cfg, _ = load_first_config()
    if a.set_key is not None:
        cfg["api_key"] = a.set_key.strip()
    if a.set_base_url is not None:
        cfg["base_url"] = a.set_base_url.strip()
    if a.configure and a.set_key is None and a.set_base_url is None:
        print("> 配置 gpt-image 接口（保存到 %s）" % CONFIG_PATHS[0])
        if cfg.get("api_key"):
            print("  当前 api_key：%s" % mask(cfg["api_key"]))
        try:
            entered = getpass.getpass("  请输入 API key（输入不回显，回车保持不变）: ").strip()
        except (EOFError, OSError):
            entered = input("  请输入 API key（回车保持不变）: ").strip()
        if entered:
            cfg["api_key"] = entered
        default_bu = cfg.get("base_url") or DEFAULT_BASE_URL
        bu = input("  base_url（回车默认 %s）: " % default_bu).strip()
        if bu:
            cfg["base_url"] = bu
    path = save_config(cfg)
    print("已保存配置到 %s（api_key=%s，base_url=%s）" % (
        path, mask(cfg.get("api_key", "")), cfg.get("base_url") or DEFAULT_BASE_URL))
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="gpt-image-2 出图（个人习惯默认参数）")
    ap.add_argument("--prompt", default=None, help="提示词（中文，按 rules 模板写；@图N 自动转 [image N]）")
    ap.add_argument("--images", nargs="*", default=[], help="参考图本地路径，顺序= @图1/@图2…（最多16张）")
    ap.add_argument("--size", default="auto",
                    help="auto（默认）| 720x1280 | 1280x720 等。注意：当前中转站忽略此参数，"
                         "比例请写进 prompt（如“（16：9）/（9：16）”）")
    ap.add_argument("--quality", default="auto", help="auto（默认）| medium | high")
    ap.add_argument("--n", type=int, default=1, help="一次出几张：定稿1（默认），探索2")
    ap.add_argument("--transparent", action="store_true",
                    help="透明底兜底模式（平时不用）：中转站一般按 prompt 里的“透明底”直接返回透明 PNG；"
                         "仅当返回图无 alpha 时用它（追加[背景指令]+本地键色抠除）。"
                         "绿幕抠图不用它，prompt 写“方便抠图的纯绿色背景”即可")
    ap.add_argument("--unkey", action="store_true",
                    help="出绿底图后本地抠键色，输出带 alpha 的透明 PNG（不改 prompt）。"
                         "图生图（带参考图）要透明底时用：prompt 写“方便抠图的纯绿色背景”+ 本选项；"
                         "文生图不要用它（prompt 直接写“透明底”即可，且质量更好）")
    ap.add_argument("--timeout", type=int, default=1000, help="请求超时秒数（默认1000）")
    ap.add_argument("--out-dir", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--name", default=None, help="输出文件名前缀（默认取提示词前几个字）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要发送的请求摘要，不调用接口")
    ap.add_argument("--configure", action="store_true", help="交互式配置 API key / base_url 并保存")
    ap.add_argument("--set-key", default=None, help="设置并保存 API key（非交互）")
    ap.add_argument("--set-base-url", default=None, help="设置并保存 base_url（非交互）")
    ap.add_argument("--show-config", action="store_true", help="查看当前配置来源（key 打码）")
    a = ap.parse_args(argv)

    if a.configure or a.set_key or a.set_base_url:
        return do_configure(a)

    key, base_url, src = resolve_config()
    if a.show_config:
        print("api_key: %s（来源：%s）" % (mask(key), src))
        print("base_url: %s" % base_url)
        print("model: %s" % DEFAULT_MODEL)
        print("配置文件查找顺序: %s" % " > ".join(CONFIG_PATHS))
        return 0

    if not a.prompt:
        ap.error("需要 --prompt（先配置 key：--set-key / --configure）")
    if len(a.images) > 16:
        ap.error("参考图最多 16 张")
    for p in a.images:
        if not os.path.isfile(p):
            ap.error("参考图不存在: %s" % p)

    api_prompt = convert_mentions(a.prompt)
    if a.transparent:
        api_prompt = build_transparent_prompt(api_prompt)
    if a.dry_run:
        endpoint = "images/edits (multipart, image[] x%d)" % len(a.images) if a.images else "images/generations (json)"
        print(json.dumps({
            "endpoint": endpoint,
            "model": DEFAULT_MODEL,
            "prompt": api_prompt,
            "size": a.size,
            "quality": a.quality,
            "output_format": "png",
            "moderation": "auto",
            "n": max(1, a.n),
        }, ensure_ascii=False, indent=2))
        print("# dry-run 未发送请求")
        return 0

    if not key:
        print("未找到 API key，请先配置（首次使用）：")
        print("  1) 非交互：python gimg.py --set-key <你的key> [--set-base-url <url>]")
        print("  2) 交互式：python gimg.py --configure")
        print("  3) 或设置环境变量 GPTIMAGE_API_KEY")
        print("  若 gptimage-ppt 已配置过（%s），本脚本会直接复用，无需再配。" % CONFIG_PATHS[1])
        return 2

    label = a.name or slug(a.prompt)
    os.makedirs(a.out_dir, exist_ok=True)
    print("生成中：%s" % (a.prompt[:80] + ("…" if len(a.prompt) > 80 else "")))
    print("  endpoint=%s size=%s quality=%s n=%d transparent=%s timeout=%ds" % (
        "edits" if a.images else "generations", a.size, a.quality, max(1, a.n), a.transparent, a.timeout))
    if a.images:
        print("  参考图: " + ", ".join(a.images))

    pngs, _ = generate(a.prompt, a.images, a.size, a.quality, a.n, a.transparent, base_url, key, a.timeout, unkey=a.unkey)
    want_transparent = a.transparent or bool(re.search(r"透明底|透明背景|transparent", a.prompt))
    for i, b in enumerate(pngs):
        suffix = "-%02d" % (i + 1) if len(pngs) > 1 else ""
        path = os.path.join(a.out_dir, "%s%s.png" % (label, suffix))
        with open(path, "wb") as f:
            f.write(b)
        try:
            w, h, _ = _png_decode(b)
            print("  -> %s (%dx%d)" % (path, w, h))
        except ValueError:
            print("  -> %s" % path)
        if want_transparent and not _png_has_alpha(b):
            print("  ⚠ 警告：prompt 要求透明底，但返回图无 alpha 通道（中转站本次未处理透明指令）。"
                  "可重试，或加 --transparent 走 [背景指令]+本地抠键色 兜底。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
