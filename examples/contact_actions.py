"""Decode model chat actions independently of their position in the reply."""

import re
import unicodedata


ACTION = re.compile(
    r"\[\s*(?:(?P<call>call\s*[:：]\s*(?:voice|video)|(?:我(?:向[^\]\n]{1,80}?)?发起了?)?(?:语音|视频)(?:通话|来电))"
    r"|(?:sticker|表情包)\s*[:：]\s*(?P<sticker>[^\]\r\n]{1,180})"
    r"|image\s*[:：]\s*(?P<image>[^\]\r\n]{1,1200})|(?P<voice>voice))\s*\]",
    re.IGNORECASE,
)
EXTENSION = re.compile(r"\.(?:gif|png|jpe?g|webp|avif)$", re.IGNORECASE)


def sticker_key(name):
    return EXTENSION.sub("", unicodedata.normalize("NFKC", name).strip()).casefold()


def sticker_options(entries):
    options = {}
    used = set()
    for entry in entries[:40]:
        if not isinstance(entry, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("id"))):
            continue
        label = EXTENSION.sub("", " ".join(str(entry.get("name") or "").split())).strip()[:100]
        label = label.translate(str.maketrans({"[": "(", "]": ")", "［": "(", "］": ")"})) or "表情包"
        key = sticker_key(label)
        if key in used:
            suffix = 2
            while sticker_key(f"{label} ({suffix})") in used:
                suffix += 1
            label = f"{label} ({suffix})"
        used.add(sticker_key(label))
        options[label] = entry["id"]
    return options


def decode(text, stickers, *, calls=False, images=False, voice=False):
    # Accept the ASCII and full-width brackets commonly produced by Chinese models.
    tags = text.translate(str.maketrans({"［": "[", "］": "]", "【": "[", "】": "]"}))
    matches = list(ACTION.finditer(tags))
    if not matches:
        return {"text": text}
    parts = []
    last = 0
    for match in matches:
        parts.append(text[last:match.start()])
        last = match.end()
    parts.append(text[last:])
    caption = "\n".join(line.rstrip() for line in "".join(parts).strip().splitlines())
    lookup = {sticker_key(name): ident for name, ident in stickers.items()}
    lookup.update({ident: ident for ident in stickers.values()})
    # Ringing is separate from the chat attachment, so one reply can include both.
    reply = {}
    for match in matches:
        target = match["call"]
        if calls and target and "call" not in reply:
            reply["call"] = "video" if "video" in target.lower() or "视频" in target else "voice"
        name = match["sticker"]
        if name and "sticker" not in reply and (ident := lookup.get(sticker_key(name))):
            reply["sticker"] = ident
        if images and match["image"] and "image_prompt" not in reply:
            reply["image_prompt"] = match["image"].strip()
        if voice and match["voice"] and caption:
            reply["voice_reply"] = True
    fallback = ("[表情包]" if reply.get("sticker") else "[图片]" if reply.get("image_prompt")
                else "视频来电" if reply.get("call") == "video" else "语音来电" if reply.get("call") else "")
    return {**reply, "text": caption or fallback}
