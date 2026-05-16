"""User Memory Explorer のバックエンド。

ユーザーメモリ（Persona/Nowaday/History）を「ユーザー理解」の観点で分析するための
集計・コホート合成・対話用コンテキスト生成をまとめる。WebUIから利用する。

WebUI(WebDigiMatsuAgent._user_memory_explorer)が描画、ここはデータ加工に専念する。
- 横断(集団): 複数ユーザーをコホートとして3層を集計 + 関心トピックの変遷
- 深掘り(個人): 1ユーザーの3層タイムライン + 感情トラジェクトリ + 要レビュー項目
- 各タブの対話: 集団/個人のメモリを合成した文脈テキストを生成（エージェントに被せる）
"""
import logging
from collections import Counter, defaultdict

import DigiM_UserMemory as dmum
import DigiM_UserMemoryBuilder as dmumb
import DigiM_GeneUserMemory as dmgum

logger = logging.getLogger(__name__)

PLUTCHIK_PRIMARY = dmgum.PLUTCHIK_PRIMARY
PLUTCHIK_SECONDARY = dmgum.PLUTCHIK_SECONDARY
BIG5_TRAITS = dmgum.BIG5_TRAITS
PLUTCHIK_JA = dict(dmumb._PLUTCHIK_JA)
BIG5_JA = dict(dmumb._BIG5_JA)

# 分析対象に含めるステータス（deletedのみ除外。pendingも"一応"含める）
_APPROVED = ("approved", "edited")  # 確定扱い
_INCLUDED = ("approved", "edited", "pending")  # 分析・集計に含める


def _is_included(item) -> bool:
    if not isinstance(item, dict):
        return False
    return (item.get("status") or "").strip().lower() != "deleted"


# ---------- データ取得 ----------
def list_users(service_id: str = "") -> list:
    """3層いずれかに登場する user_id を昇順で返す。"""
    users = set()
    for layer in dmum.LAYERS:
        try:
            for r in dmum.load_all(layer, service_id=service_id):
                uid = (r.get("user_id") or "").strip()
                if uid:
                    users.add(uid)
        except Exception as e:
            logger.warning(f"[um_explorer] list_users {layer}失敗: {e}")
    return sorted(users)


def load_bundle(user_id: str, service_id: str = "") -> dict:
    """1ユーザーの3層を取得。nowaday/historyは時系列降順。"""
    persona = dmum.get_one("persona", {"service_id": service_id, "user_id": user_id}) if service_id \
        else _first(dmum.load_all("persona", user_id=user_id))
    nowaday = dmum.load_all("nowaday", service_id=service_id, user_id=user_id)
    history = dmum.load_all("history", service_id=service_id, user_id=user_id)
    nowaday = [m for m in nowaday if (m.get("active") or "Y") == "Y"]
    history = [h for h in history if (h.get("active") or "Y") == "Y"]
    nowaday.sort(key=lambda r: r.get("generated_at") or r.get("period") or "", reverse=True)
    history.sort(key=lambda r: r.get("create_date") or "", reverse=True)
    return {"persona": persona or {}, "nowaday": nowaday, "history": history}


def _first(lst):
    return lst[0] if lst else {}


# ---------- コホート絞り込み ----------
def resolve_cohort(user_ids=None, service_id: str = "", interest_kw: str = "",
                   emotion_key: str = "", big5_trait: str = "", big5_min: float = None) -> list:
    """条件でユーザーを絞り込む。user_ids未指定なら全ユーザーが母集団。

    interest_kw : Persona.recurring_interests / Nowaday.recurring_topics に部分一致
    emotion_key : 最新Nowaday.basic_emotions[emotion_key] > 0 のユーザー
    big5_trait + big5_min : Persona.big5[trait].score >= big5_min
    """
    base = list(user_ids) if user_ids else list_users(service_id)
    out = []
    for uid in base:
        b = load_bundle(uid, service_id)
        if interest_kw:
            kws = _user_interest_terms(b)
            if not any(interest_kw.strip() in t for t in kws):
                continue
        if emotion_key:
            be = (b["nowaday"][0].get("basic_emotions") if b["nowaday"] else {}) or {}
            try:
                if float(be.get(emotion_key, 0) or 0) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        if big5_trait and big5_min is not None:
            item = (b["persona"].get("big5") or {}).get(big5_trait) or {}
            try:
                if float(item.get("score", 0) or 0) < float(big5_min):
                    continue
            except (TypeError, ValueError):
                continue
        out.append(uid)
    return out


def _user_interest_terms(bundle: dict) -> list:
    terms = []
    for it in (bundle["persona"].get("recurring_interests") or []):
        if isinstance(it, dict) and it.get("label"):
            terms.append(str(it["label"]).strip())
    for m in bundle["nowaday"]:
        for t in (m.get("recurring_topics") or []):
            terms.append(str(t).strip())
    return [t for t in terms if t]


# ---------- 横断集計 ----------
def agg_big5(user_ids: list, service_id: str = "") -> dict:
    """Big5 を特性ごとに集計（deletedのみ除外、pendingも含む）。

    {trait:{mean,n,n_pending,per_user:[(uid,score,status)]}}。
    """
    acc = {t: [] for t in BIG5_TRAITS}
    for uid in user_ids:
        big5 = (load_bundle(uid, service_id)["persona"].get("big5") or {})
        for t in BIG5_TRAITS:
            item = big5.get(t) or {}
            if not _is_included(item):
                continue
            st = (item.get("status") or "").strip().lower()
            try:
                acc[t].append((uid, float(item.get("score", 0.5) or 0.5), st))
            except (TypeError, ValueError):
                pass
    out = {}
    for t, triples in acc.items():
        scores = [s for _, s, _ in triples]
        out[t] = {
            "mean": round(sum(scores) / len(scores), 3) if scores else None,
            "n": len(scores),
            "n_pending": sum(1 for _, _, st in triples if st == "pending"),
            "per_user": [(u, s) for u, s, _ in triples],
        }
    return out


def agg_basic_emotions(user_ids: list, service_id: str = "", period: str = "") -> dict:
    """最新（or 指定period）の Nowaday.basic_emotions をユーザー平均。{emotion:mean}。"""
    sums = {e: 0.0 for e in PLUTCHIK_PRIMARY}
    n = 0
    for uid in user_ids:
        nws = load_bundle(uid, service_id)["nowaday"]
        rec = None
        if period:
            rec = next((m for m in nws if (m.get("period") or "") == period), None)
        elif nws:
            rec = nws[0]
        if not rec:
            continue
        be = rec.get("basic_emotions") or {}
        if not isinstance(be, dict):
            continue
        n += 1
        for e in PLUTCHIK_PRIMARY:
            try:
                sums[e] += float(be.get(e, 0) or 0)
            except (TypeError, ValueError):
                pass
    return {e: (round(sums[e] / n, 3) if n else 0.0) for e in PLUTCHIK_PRIMARY}


def agg_secondary_emotions(user_ids: list, service_id: str = "", period: str = "") -> Counter:
    c = Counter()
    for uid in user_ids:
        nws = load_bundle(uid, service_id)["nowaday"]
        rec = None
        if period:
            rec = next((m for m in nws if (m.get("period") or "") == period), None)
        elif nws:
            rec = nws[0]
        if not rec:
            continue
        for s in (rec.get("secondary_emotions") or []):
            if isinstance(s, str) and s.strip():
                c[s.strip().lower()] += 1
    return c


def agg_interests(user_ids: list, service_id: str = "", top_n: int = 30) -> list:
    """Persona.recurring_interests + 最新Nowaday.recurring_topics の出現頻度トップN。"""
    c = Counter()
    for uid in user_ids:
        b = load_bundle(uid, service_id)
        for it in (b["persona"].get("recurring_interests") or []):
            if isinstance(it, dict) and it.get("label") and _is_included(it):
                c[str(it["label"]).strip()] += 1
        if b["nowaday"]:
            for t in (b["nowaday"][0].get("recurring_topics") or []):
                if str(t).strip():
                    c[str(t).strip()] += 1
    return c.most_common(top_n)


def topic_evolution(user_ids: list, service_id: str = "") -> dict:
    """期間ごとの recurring/emerging/declining をコホート横断で集計。

    Returns: {"periods":[...昇順...],
              "recurring":{period:Counter}, "emerging":{...}, "declining":{...}}
    """
    rec = defaultdict(Counter)
    eme = defaultdict(Counter)
    dec = defaultdict(Counter)
    periods = set()
    for uid in user_ids:
        for m in load_bundle(uid, service_id)["nowaday"]:
            p = (m.get("period") or "").strip()
            if not p:
                continue
            periods.add(p)
            for t in (m.get("recurring_topics") or []):
                if str(t).strip():
                    rec[p][str(t).strip()] += 1
            for t in (m.get("emerging") or []):
                if str(t).strip():
                    eme[p][str(t).strip()] += 1
            for t in (m.get("declining") or []):
                if str(t).strip():
                    dec[p][str(t).strip()] += 1
    return {
        "periods": sorted(periods),
        "recurring": dict(rec),
        "emerging": dict(eme),
        "declining": dict(dec),
    }


# ---------- 個人トラジェクトリ ----------
def user_emotion_trajectory(user_id: str, service_id: str = "") -> list:
    """History を時系列昇順で [(create_date, [emotion_keys])] に。"""
    hs = load_bundle(user_id, service_id)["history"]
    out = []
    for h in sorted(hs, key=lambda r: r.get("create_date") or ""):
        emos = [e for e in (h.get("emotions") or []) if isinstance(e, str)]
        out.append((str(h.get("create_date") or "")[:10],
                    str(h.get("topic") or ""), emos))
    return out


def user_nowaday_emotion_series(user_id: str, service_id: str = "") -> list:
    """Nowaday を period 昇順で [(period, {emotion:intensity})] に。"""
    nws = load_bundle(user_id, service_id)["nowaday"]
    out = []
    for m in sorted(nws, key=lambda r: r.get("period") or ""):
        be = m.get("basic_emotions") or {}
        out.append((str(m.get("period") or ""),
                    {e: float(be.get(e, 0) or 0) for e in PLUTCHIK_PRIMARY}))
    return out


def persona_review_items(user_id: str, service_id: str = "") -> dict:
    """pending の Big5 / リスト項目（要レビュー）を抽出。"""
    p = load_bundle(user_id, service_id)["persona"]
    big5_pending = []
    for t in BIG5_TRAITS:
        item = (p.get("big5") or {}).get(t) or {}
        if (item.get("status") or "").strip().lower() == "pending":
            big5_pending.append((t, item.get("score"), item.get("confidence")))
    list_pending = {}
    for f in ("expertise", "recurring_interests", "values_principles",
              "constraints", "communication_style", "avoid_topics"):
        items = [it.get("label") for it in (p.get(f) or [])
                 if isinstance(it, dict) and (it.get("status") or "").strip().lower() == "pending"
                 and it.get("label")]
        if items:
            list_pending[f] = items
    return {"big5": big5_pending, "lists": list_pending}


# ---------- 対話用コンテキスト ----------
def build_user_context(user_id: str, service_id: str = "") -> str:
    """個人の3層を「対話相手についての情報」テキストに（既存ビルダー再利用）。"""
    try:
        text, _used, _meta = dmumb.build_context_text(
            service_id, user_id, list(dmum.LAYERS), query_text="")
        return text or ""
    except Exception as e:
        logger.warning(f"[um_explorer] build_user_context失敗 {user_id}: {e}")
        return ""


def build_cohort_context(user_ids: list, service_id: str = "",
                         history_sample_per_user: int = 1,
                         max_chars: int = 4000) -> str:
    """コホートを統計合成した「集団プロファイル」テキスト。

    個人サマリの羅列ではなく Big5平均/感情平均/関心トップN + 代表History抜粋。
    """
    if not user_ids:
        return ""
    n = len(user_ids)
    big5 = agg_big5(user_ids, service_id)
    emo = agg_basic_emotions(user_ids, service_id)
    sec = agg_secondary_emotions(user_ids, service_id)
    interests = agg_interests(user_ids, service_id, top_n=15)

    parts = [f"# 対象集団について（{n}人）",
             "以下はこの集団を統計的に合成したプロファイルです。個人ではなく集団傾向として扱ってください。",
             ""]

    b5 = [f"{BIG5_JA.get(t, t)}={d['mean']:.2f}(n={d['n']})"
          for t, d in big5.items() if d.get("mean") is not None]
    if b5:
        parts.append("## Big5平均\n・" + "、".join(b5))

    top_emo = sorted(((e, v) for e, v in emo.items() if v > 0.05),
                     key=lambda x: -x[1])[:5]
    if top_emo:
        parts.append("## 感情傾向（平均強度）\n・"
                     + "、".join(f"{PLUTCHIK_JA.get(e, e)}({v:.2f})" for e, v in top_emo))
    if sec:
        parts.append("## よくある二次感情\n・"
                     + "、".join(f"{PLUTCHIK_JA.get(k, k)}({c})" for k, c in sec.most_common(5)))

    if interests:
        parts.append("## 共通の関心トップ\n・"
                     + "、".join(f"{w}({c})" for w, c in interests))

    # 代表History抜粋（各ユーザー最新N件、合計文字数で打ち切り）
    excerpts = []
    total = 0
    for uid in user_ids:
        hs = load_bundle(uid, service_id)["history"][:history_sample_per_user]
        for h in hs:
            line = f"・[{str(h.get('create_date') or '')[:10]}][{h.get('topic','')[:24]}] {str(h.get('excerpt') or '')[:120]}"
            if total + len(line) > max_chars:
                break
            excerpts.append(line)
            total += len(line)
    if excerpts:
        parts.append("## 代表的な発言抜粋\n" + "\n".join(excerpts))

    text = "\n\n".join(parts) + "\n\n"
    if len(text) > max_chars:
        text = text[:max_chars - 1] + "…"
    return text


# ---------- グループ理解（横断）用 ----------
import DigiM_Util as dmu

# ワードクラウド/キーワード抽出用ストップワード（最小限）
_STOP_WORDS = [
    "こと", "もの", "ため", "それ", "これ", "あれ", "よう", "ところ", "とき",
    "人", "自分", "相手", "方", "今", "前", "後", "場合", "必要", "重要", "意味",
    "問題", "結果", "状況", "全体", "部分", "感じ", "点", "面", "的", "性", "化",
    "情報", "データ", "内容", "対象", "傾向", "話", "気", "目", "手", "力",
]


def user_big5_scores(user_id: str, service_id: str = "") -> dict:
    """approved+pending（deletedのみ除外）のBig5スコア。欠損は0.5。{trait: score}。"""
    big5 = (load_bundle(user_id, service_id)["persona"].get("big5") or {})
    out = {}
    for t in BIG5_TRAITS:
        it = big5.get(t) or {}
        if isinstance(it, dict) and _is_included(it):
            try:
                out[t] = float(it.get("score", 0.5) or 0.5)
            except (TypeError, ValueError):
                out[t] = 0.5
        else:
            out[t] = 0.5
    return out


def cohort_big5_stats(user_ids: list, service_id: str = "") -> dict:
    """Big5特性ごとに max/mean/min を返す。{trait:{max,mean,min,n}}。"""
    acc = {t: [] for t in BIG5_TRAITS}
    for uid in user_ids:
        sc = user_big5_scores(uid, service_id)
        for t in BIG5_TRAITS:
            acc[t].append(sc[t])
    out = {}
    for t, vs in acc.items():
        out[t] = {
            "max": round(max(vs), 3) if vs else 0.0,
            "mean": round(sum(vs) / len(vs), 3) if vs else 0.0,
            "min": round(min(vs), 3) if vs else 0.0,
            "n": len(vs),
        }
    return out


def _latest_nowaday(uid: str, service_id: str = "") -> dict:
    nws = load_bundle(uid, service_id)["nowaday"]
    return nws[0] if nws else {}


def cohort_basic_emotion_stats(user_ids: list, service_id: str = "") -> dict:
    """最新Nowadayの基本8感情ごとに max/mean/min。{emotion:{max,mean,min,n}}。"""
    acc = {e: [] for e in PLUTCHIK_PRIMARY}
    for uid in user_ids:
        be = (_latest_nowaday(uid, service_id).get("basic_emotions") or {})
        if not isinstance(be, dict):
            continue
        for e in PLUTCHIK_PRIMARY:
            try:
                acc[e].append(float(be.get(e, 0) or 0))
            except (TypeError, ValueError):
                acc[e].append(0.0)
    out = {}
    for e, vs in acc.items():
        out[e] = {
            "max": round(max(vs), 3) if vs else 0.0,
            "mean": round(sum(vs) / len(vs), 3) if vs else 0.0,
            "min": round(min(vs), 3) if vs else 0.0,
            "n": len(vs),
        }
    return out


def persona_text(user_id: str, service_id: str = "") -> str:
    """1ユーザーのPersonaを1テキストに連結（role/summary/各リストlabel）。"""
    p = load_bundle(user_id, service_id)["persona"] or {}
    parts = [str(p.get("role") or ""), str(p.get("summary_text") or "")]
    for f in ("expertise", "recurring_interests", "values_principles",
              "constraints", "communication_style", "avoid_topics"):
        for it in (p.get(f) or []):
            if isinstance(it, dict) and it.get("label") and _is_included(it):
                parts.append(str(it["label"]))
    return "\n".join(x for x in parts if x.strip())


def nowaday_text(user_id: str, service_id: str = "") -> str:
    """1ユーザーの最新Nowadayを1テキストに連結。"""
    m = _latest_nowaday(user_id, service_id)
    if not m:
        return ""
    parts = [str(m.get("summary_text") or "")]
    for f in ("recurring_topics", "emerging", "declining", "shifts"):
        parts += [str(x) for x in (m.get(f) or [])]
    return "\n".join(x for x in parts if x.strip())


def nowaday_field_corpus(user_ids: list, service_id: str = "") -> dict:
    """5フィールド別に全ユーザー分テキストを連結。{summary,recurring,emerging,declining,shifts}。"""
    fields = {"summary": [], "recurring": [], "emerging": [],
              "declining": [], "shifts": []}
    fmap = {"summary": "summary_text", "recurring": "recurring_topics",
            "emerging": "emerging", "declining": "declining", "shifts": "shifts"}
    for uid in user_ids:
        m = _latest_nowaday(uid, service_id)
        if not m:
            continue
        for k, src in fmap.items():
            v = m.get(src)
            if k == "summary":
                if v:
                    fields[k].append(str(v))
            else:
                fields[k] += [str(x) for x in (v or [])]
    return {k: "\n".join(v) for k, v in fields.items()}


def cohort_history_emotion_totals(user_ids: list, service_id: str = "") -> dict:
    """選択ユーザー全Historyのプルチック感情を合計カウント。{emotion_key: count}（降順dict）。"""
    c = Counter()
    for uid in user_ids:
        for h in load_bundle(uid, service_id)["history"]:
            for e in (h.get("emotions") or []):
                if isinstance(e, str) and e.strip():
                    c[e.strip().lower()] += 1
    return dict(c.most_common())


def word_freq(text: str, top_n: int = 80) -> dict:
    """テキストからMeCab名詞を抽出し頻度dictを返す（ワードクラウド用）。"""
    if not text or not text.strip():
        return {}
    try:
        toks = dmu.tokenize_Owakati(text, mode="Default",
                                    stop_words=_STOP_WORDS, grammer=("名詞",))
    except Exception as e:
        logger.warning(f"[um_explorer] tokenize失敗: {e}")
        return {}
    c = Counter(t for t in toks if len(t) >= 2 and not t.isdigit())
    return dict(c.most_common(top_n))


def cluster_users(items: list, n_clusters: int = 3, service_id: str = "") -> dict:
    """items=[(user_id, text)] を埋め込み→2D→KMeans。

    Returns: {"df": DataFrame[user,Cluster,X1,X2,Big5...], "info": str,
              "summary": str(LLM解説用)} / 失敗時 {"error": str}
    """
    import pandas as pd
    import DigiM_VAnalytics as dmva
    rows = [(u, t) for u, t in items if t and t.strip()]
    if len(rows) < 2:
        return {"error": "テキストのあるユーザーが2人未満です（クラスタリング不可）"}
    k = max(2, min(int(n_clusters), len(rows)))
    recs = []
    for u, t in rows:
        try:
            vec = dmu.embed_text(t.replace("\n", " ")[:6000])
        except Exception as e:
            logger.warning(f"[um_explorer] embed失敗 {u}: {e}")
            continue
        recs.append({"id": u, "user": u, "value_text": t[:400],
                     "vector_data_value_text": vec})
    if len(recs) < 2:
        return {"error": "埋め込み生成に失敗しました"}
    df = pd.DataFrame(recs)
    try:
        df, dim_info = dmva.reduce_dimensions(
            df, vector_col="vector_data_value_text", method="PCA")
        df, cl_info = dmva.apply_clustering(
            df, method="K-Means", params={"n_clusters": k})
    except Exception as e:
        return {"error": f"クラスタリング失敗: {e}"}
    # Big5列を付与
    for t in BIG5_TRAITS:
        df[BIG5_JA.get(t, t)] = df["user"].map(
            lambda u: round(user_big5_scores(u, service_id)[t], 2))
    df["X1"] = df["X1"].round(3)
    df["X2"] = df["X2"].round(3)
    summary = dmva.build_cluster_summary(df, text_col="value_text")
    disp_cols = ["user", "Cluster", "X1", "X2"] + [BIG5_JA.get(t, t) for t in BIG5_TRAITS]
    return {"df": df[disp_cols].rename(columns={"user": "ユーザー", "Cluster": "クラスタ"}),
            "info": f"{dim_info} / {cl_info}", "summary": summary}


def explain_clusters(summary_text: str, agent_file: str = "agent_23DataAnalyst.json",
                     engine: str = "") -> str:
    """build_cluster_summary のテキストをLLMで解説（Knowledge Explorer同様）。"""
    if not summary_text or not summary_text.strip():
        return ""
    import DigiM_Agent as dma
    try:
        agent = dma.DigiM_Agent(agent_file)
        if engine and engine in (agent.agent.get("ENGINE", {}).get("LLM", {})):
            agent.agent["ENGINE"]["LLM"]["DEFAULT"] = engine
        try:
            tmpl = agent.set_prompt_template("Cluster Analyst")
        except Exception:
            tmpl = ""
        resp = ""
        for _, ch, _ in agent.generate_response("LLM", f"{tmpl}\n{summary_text}", [], stream_mode=False):
            if ch:
                resp += ch
        return resp
    except Exception as e:
        logger.warning(f"[um_explorer] explain_clusters失敗: {e}")
        return f"(解説生成エラー: {e})"


def build_group_twin_prompt(user_ids: list, service_id: str = "",
                            engine_cfg: dict = None) -> str:
    """対象集団のPersona/NowadayからグループツインのベースシステムプロンプトをLLM生成。

    engine_cfg を渡せばそのLLMで生成（無ければ agent_23DataAnalyst.json 既定）。
    """
    if not user_ids:
        return ""
    # 素材: 各ユーザーのpersona/nowaday要約を圧縮連結
    mats = []
    for uid in user_ids[:30]:
        p = load_bundle(uid, service_id)["persona"] or {}
        nw = _latest_nowaday(uid, service_id)
        mats.append(
            f"[{uid}] role={p.get('role','')} / persona={str(p.get('summary_text') or '')[:300]}"
            f" / nowaday={str(nw.get('summary_text') or '')[:200]}"
        )
    payload = (
        "以下は対象ユーザー群のPersona/Nowaday要約です。これらを統合し、"
        "この集団の代表的な人物像・価値観・関心・最近の傾向を表す"
        "「グループツイン」のシステムプロンプト（日本語、800字以内、二人称や前置き無しで"
        "『あなたは〜な集団を代表する人物です』の形式）を作成してください。\n\n"
        + "\n".join(mats)
    )
    try:
        import DigiM_FoundationModel as dmfm
        if engine_cfg and engine_cfg.get("FUNC_NAME"):
            resp = ""
            for _p, _r, _c in dmfm.call_function_by_name(
                    engine_cfg["FUNC_NAME"], payload,
                    "あなたは集団プロファイルを統合する分析者です。", engine_cfg,
                    [], [], {}, False):
                if _r:
                    resp += _r
            return resp.strip()
        import DigiM_Agent as dma
        agent = dma.DigiM_Agent("agent_23DataAnalyst.json")
        resp = ""
        for _, ch, _ in agent.generate_response("LLM", payload, [], stream_mode=False):
            if ch:
                resp += ch
        return resp.strip()
    except Exception as e:
        logger.warning(f"[um_explorer] build_group_twin_prompt失敗: {e}")
        return ""
