from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..storage.repositories import RecommendationRepository

# i.pximg.net rejects requests without a pixiv Referer, and a local file:// page
# cannot set one. i.pixiv.re is the community reverse proxy that serves the same
# paths without the Referer requirement; <meta referrer no-referrer> covers the
# rest. The original URL is kept in data-src for tools that can set headers.
_PXIMG_HOST = 'i.pximg.net'
_PXIMG_MIRROR = 'i.pixiv.re'

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="referrer" content="no-referrer">
<title>pixiv artist recommendations — {run_id}</title>
<style>
  body {{ font-family: "Segoe UI", "Yu Gothic UI", sans-serif; background: #f4f5f7; margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; }} .meta {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 14px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }}
  .card.dismissed {{ opacity: .35; }}
  .head {{ display: flex; align-items: center; gap: 10px; }}
  .avatar {{ width: 44px; height: 44px; border-radius: 50%; object-fit: cover; background: #ddd; }}
  .name {{ font-weight: 600; text-decoration: none; color: #1a73e8; }}
  .score {{ margin-left: auto; font-variant-numeric: tabular-nums; color: #333; }}
  .thumbs {{ display: flex; gap: 6px; margin: 10px 0; }}
  .thumbs a {{ flex: 1; }}
  .thumbs img {{ width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 6px; background: #eee; }}
  .reasons {{ font-size: 12px; color: #777; max-height: 60px; overflow: auto; }}
  .actions {{ margin-top: 10px; display: flex; gap: 8px; }}
  button {{ border: 1px solid #ccc; background: #fafafa; border-radius: 6px; padding: 4px 12px; cursor: pointer; }}
  button:hover {{ background: #eee; }}
  .status {{ font-size: 12px; color: #999; margin-left: auto; align-self: center; }}
</style>
</head>
<body>
<h1>pixiv 画师推荐 — {run_id}</h1>
<div class="meta">seed={seed_user_id} · mode={mode} · created={created_at} · {item_count} artists
 · 反馈按钮需要本地 API 运行中（python -m pixiv_artist_recsys serve-api，默认 {api_base}）</div>
<div class="grid">
{cards}
</div>
<script>
const API_BASE = {api_base_json};
const SEED_USER_ID = {seed_user_id};
const RUN_ID = {run_id_json};
async function feedback(btn, artistId, action) {{
  const card = btn.closest('.card');
  const status = card.querySelector('.status');
  status.textContent = '...';
  try {{
    const resp = await fetch(API_BASE + '/feedback', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{seed_user_id: SEED_USER_ID, artist_user_id: artistId, action: action, source_run_id: RUN_ID}}),
    }});
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    status.textContent = action + ' ✓';
    card.classList.add('dismissed');
  }} catch (err) {{
    status.textContent = action + ' 失败: ' + err.message;
  }}
}}
</script>
</body>
</html>
"""

_CARD_TEMPLATE = """<div class="card" id="artist-{artist_id}">
  <div class="head">
    <img class="avatar" src="{avatar}" alt="" loading="lazy">
    <a class="name" href="https://www.pixiv.net/users/{artist_id}" target="_blank" rel="noopener">{name}</a>
    <span class="score" title="confidence {confidence}">{score}</span>
  </div>
  <div class="thumbs">{thumbs}</div>
  <div class="reasons">{reasons}</div>
  <div class="actions">
    <button onclick="feedback(this, {artist_id}, 'dislike')">dislike</button>
    <button onclick="feedback(this, {artist_id}, 'block')">block</button>
    <span class="status"></span>
  </div>
</div>"""

_THUMB_TEMPLATE = (
    '<a href="https://www.pixiv.net/artworks/{illust_id}" target="_blank" rel="noopener">'
    '<img src="{src}" data-src="{original}" alt="{title}" loading="lazy"></a>'
)


def _mirror_url(url: str) -> str:
    return (url or '').replace(_PXIMG_HOST, _PXIMG_MIRROR)


@dataclass(slots=True)
class HtmlReportBuilder:
    repository: RecommendationRepository
    api_base: str = 'http://127.0.0.1:8787'

    def build_for_run(self, *, run_id: str) -> str:
        run = self.repository.fetch_recommendation_run(run_id=run_id)
        if run is None:
            raise ValueError(f'run not found: {run_id}')
        _, seed_user_id, mode, created_at = run
        items = self.repository.fetch_recommendation_items(run_id=run_id)

        artist_ids = [artist_id for artist_id, _, _, _, _ in items]
        artists = self.repository.fetch_artists_by_ids(artist_user_ids=artist_ids)
        illusts_by_artist = self.repository.fetch_illusts_for_artists(artist_user_ids=artist_ids)

        cards: list[str] = []
        for artist_id, score, confidence, reasons, top_illust_ids in items:
            artist = artists.get(artist_id)
            name = html.escape(artist.name if artist else f'artist-{artist_id}')
            avatar = _mirror_url(artist.profile_image_url) if artist else ''
            illusts = {illust.illust_id: illust for illust in illusts_by_artist.get(artist_id, [])}
            chosen = [iid for iid in top_illust_ids if iid in illusts][:3]
            if len(chosen) < 3:
                for illust in illusts_by_artist.get(artist_id, []):
                    if illust.illust_id not in chosen:
                        chosen.append(illust.illust_id)
                    if len(chosen) >= 3:
                        break
            thumbs = ''.join(
                _THUMB_TEMPLATE.format(
                    illust_id=iid,
                    src=html.escape(_mirror_url(illusts[iid].image_url)),
                    original=html.escape(illusts[iid].image_url),
                    title=html.escape(illusts[iid].title),
                )
                for iid in chosen
            ) or '<span style="color:#bbb;font-size:12px">no local thumbnails</span>'
            cards.append(
                _CARD_TEMPLATE.format(
                    artist_id=artist_id,
                    avatar=html.escape(avatar),
                    name=name,
                    score=f'{score:.3f}',
                    confidence=f'{confidence:.3f}',
                    thumbs=thumbs,
                    reasons=html.escape(' · '.join(reasons)),
                )
            )

        return _PAGE_TEMPLATE.format(
            run_id=html.escape(run_id),
            run_id_json=json.dumps(run_id),
            seed_user_id=int(seed_user_id),
            mode=html.escape(mode),
            created_at=html.escape(created_at),
            item_count=len(items),
            api_base=html.escape(self.api_base),
            api_base_json=json.dumps(self.api_base),
            cards='\n'.join(cards),
        )

    def write_for_run(self, *, run_id: str, output_path: str | Path) -> dict[str, Any]:
        content = self.build_for_run(run_id=run_id)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return {'run_id': run_id, 'output_path': str(path), 'bytes': len(content.encode('utf-8'))}
