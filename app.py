import subprocess
import sys
import os
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime

# Install Playwright browser once on cold start
@st.cache_resource(show_spinner="正在初始化爬蟲引擎…")
def install_playwright():
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True
    )
    return result.returncode

try:
    install_playwright()
except Exception as e:
    st.error(f"Playwright 初始化失敗：{e}")
    st.stop()

# Load secrets into env vars (Streamlit Cloud)
try:
    for key in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AI_PROVIDER"]:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass  # local dev — env vars set directly

import database as db
import scraper
import ai_chat

# ── Init ──────────────────────────────────────────────────────────────────────

db.init_db()

st.set_page_config(
    page_title="PriceWise",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .product-card {
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        background: #fafafa;
    }
    .price-tag { font-size: 1.4rem; font-weight: 700; color: #e53e3e; }
    .stat-box  { background: #f0f4ff; border-radius: 8px; padding: 8px 12px; text-align: center; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar nav ───────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("💰 PriceWise")
    page = st.radio(
        "導航",
        ["🔍 搜尋商品", "📋 追蹤清單", "📈 價格分析", "🗂️ 商品群組", "🤖 AI 對話"],
        label_visibility="collapsed",
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: 搜尋商品
# ═══════════════════════════════════════════════════════════════════════════════

if page == "🔍 搜尋商品":
    st.header("🔍 搜尋商品")
    st.caption("輸入 Momo 商品網址或關鍵字")

    col_input, col_btn = st.columns([5, 1])
    with col_input:
        query = st.text_input("", placeholder="https://www.momoshop.com.tw/... 或關鍵字", label_visibility="collapsed")
    with col_btn:
        search_clicked = st.button("搜尋", use_container_width=True, type="primary")

    if search_clicked and query:
        with st.spinner("爬取中，請稍候…"):
            try:
                results = scraper.scrape_sync(query)
            except Exception as e:
                st.error(f"爬取失敗：{e}")
                results = []

        if not results:
            st.warning("未找到商品，請換個關鍵字或確認網址。")
        else:
            st.success(f"找到 {len(results)} 筆結果")
            for r in results:
                if r.error:
                    st.error(r.error)
                    continue

                with st.container():
                    c1, c2, c3 = st.columns([1, 4, 2])
                    with c1:
                        if r.image_url:
                            st.image(r.image_url, width=90)
                    with c2:
                        st.markdown(f"**{r.name}**")
                        st.markdown(f'<span class="price-tag">NT$ {r.price:,.0f}</span>', unsafe_allow_html=True)
                        st.caption(r.url[:60] + "…" if len(r.url) > 60 else r.url)
                    with c3:
                        if st.button("＋ 加入追蹤", key=f"add_{r.url}"):
                            pid = db.upsert_product(r.name, r.url, "momo", r.image_url)
                            db.add_price(pid, r.price, r.in_stock)
                            st.success("已加入追蹤！")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: 追蹤清單
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📋 追蹤清單":
    st.header("📋 追蹤清單")

    products = db.get_all_products()

    if not products:
        st.info("尚無追蹤商品。前往「搜尋商品」新增。")
    else:
        col_refresh, col_spacer = st.columns([2, 8])
        with col_refresh:
            if st.button("🔄 全體更新價格", type="primary", use_container_width=True):
                progress = st.progress(0, text="更新中…")
                for i, p in enumerate(products):
                    try:
                        results = scraper.scrape_sync(p["url"])
                        if results and not results[0].error:
                            r = results[0]
                            db.upsert_product(r.name, r.url, "momo", r.image_url)
                            db.add_price(p["id"], r.price, r.in_stock)
                    except Exception:
                        pass
                    progress.progress((i + 1) / len(products), text=f"更新中 {i+1}/{len(products)}")
                st.success("全部更新完成！")
                st.rerun()

        st.divider()

        for p in products:
            with st.expander(f"**{p['name']}**　NT$ {p['latest_price']:,.0f}" if p["latest_price"] else f"**{p['name']}**　— 尚無價格", expanded=False):
                c1, c2 = st.columns([3, 1])
                with c1:
                    stats = db.get_price_stats(p["id"])
                    if stats["data_points"]:
                        m1, m2, m3 = st.columns(3)
                        m1.metric("均價", f"NT$ {stats['avg_price']:,.0f}")
                        m2.metric("最低", f"NT$ {stats['min_price']:,.0f}")
                        m3.metric("最高", f"NT$ {stats['max_price']:,.0f}")
                    st.caption(f"最後更新：{p['last_checked'] or '—'}")

                    groups = db.get_all_groups()
                    product_groups = [g["id"] for g in db.get_product_groups(p["id"])]
                    group_options = {g["name"]: g["id"] for g in groups}
                    selected = st.multiselect(
                        "群組", list(group_options.keys()),
                        default=[g["name"] for g in db.get_product_groups(p["id"])],
                        key=f"grp_{p['id']}",
                    )
                    if st.button("更新群組", key=f"savegrp_{p['id']}"):
                        for gname, gid in group_options.items():
                            if gname in selected:
                                db.assign_group(p["id"], gid)
                            else:
                                db.remove_group(p["id"], gid)
                        st.success("群組已更新")

                with c2:
                    if p["image_url"]:
                        st.image(p["image_url"], width=100)
                    if st.button("🗑️ 移除", key=f"del_{p['id']}", type="secondary"):
                        db.delete_product(p["id"])
                        st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: 價格分析
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "📈 價格分析":
    st.header("📈 價格分析")

    products = db.get_all_products()
    if not products:
        st.info("尚無追蹤商品。")
    else:
        product_map = {p["name"]: p["id"] for p in products}
        selected_name = st.selectbox("選擇商品", list(product_map.keys()))
        pid = product_map[selected_name]

        history = db.get_price_history(pid)
        stats = db.get_price_stats(pid)

        if not history:
            st.warning("此商品尚無價格記錄。")
        else:
            df = pd.DataFrame([dict(h) for h in history])
            df["scraped_at"] = pd.to_datetime(df["scraped_at"])

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("目前價格", f"NT$ {df['price'].iloc[-1]:,.0f}")
            m2.metric("均價",     f"NT$ {stats['avg_price']:,.0f}")
            m3.metric("最低價",   f"NT$ {stats['min_price']:,.0f}")
            m4.metric("記錄筆數", stats["data_points"])

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["scraped_at"], y=df["price"],
                mode="lines+markers", name="價格",
                line=dict(color="#4F8EF7", width=2),
                marker=dict(size=6),
            ))
            fig.add_hline(y=stats["avg_price"], line_dash="dash",
                          line_color="orange", annotation_text="均價")
            fig.add_hline(y=stats["min_price"], line_dash="dot",
                          line_color="green", annotation_text="最低")
            fig.update_layout(
                title=f"{selected_name} 歷史價格趨勢",
                xaxis_title="日期", yaxis_title="價格 (NT$)",
                hovermode="x unified", height=420,
            )
            st.plotly_chart(fig, use_container_width=True)

        # 多商品比較
        st.subheader("多商品比較")
        compare_names = st.multiselect("選擇要比較的商品", list(product_map.keys()), max_selections=6)
        if compare_names:
            fig2 = go.Figure()
            for name in compare_names:
                h = db.get_price_history(product_map[name])
                if h:
                    df2 = pd.DataFrame([dict(r) for r in h])
                    df2["scraped_at"] = pd.to_datetime(df2["scraped_at"])
                    fig2.add_trace(go.Scatter(x=df2["scraped_at"], y=df2["price"],
                                              mode="lines+markers", name=name))
            fig2.update_layout(title="商品價格比較", height=400,
                               xaxis_title="日期", yaxis_title="價格 (NT$)")
            st.plotly_chart(fig2, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: 商品群組
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🗂️ 商品群組":
    st.header("🗂️ 商品群組")

    # create group
    with st.form("new_group"):
        col1, col2 = st.columns([4, 1])
        with col1:
            new_group_name = st.text_input("新增群組", placeholder="例：3C、咖啡設備")
        with col2:
            st.write("")
            submitted = st.form_submit_button("新增", use_container_width=True)
        if submitted and new_group_name:
            db.create_group(new_group_name)
            st.success(f"群組「{new_group_name}」已建立")
            st.rerun()

    groups = db.get_all_groups()
    if not groups:
        st.info("尚無群組，請先新增。")
    else:
        tabs = st.tabs([g["name"] for g in groups])
        for tab, group in zip(tabs, groups):
            with tab:
                items = db.get_products_in_group(group["id"])
                if not items:
                    st.caption("此群組尚無商品")
                    continue

                # matrix / comparison table
                rows = []
                for p in items:
                    stats = db.get_price_stats(p["id"])
                    rows.append({
                        "商品名稱": p["name"],
                        "目前價格": p["latest_price"],
                        "均價": stats.get("avg_price"),
                        "最低價": stats.get("min_price"),
                        "最高價": stats.get("max_price"),
                        "記錄筆數": stats.get("data_points", 0),
                    })
                df = pd.DataFrame(rows)
                st.dataframe(
                    df.style.format({
                        "目前價格": "NT$ {:,.0f}",
                        "均價":     "NT$ {:,.0f}",
                        "最低價":   "NT$ {:,.0f}",
                        "最高價":   "NT$ {:,.0f}",
                    }, na_rep="—"),
                    use_container_width=True,
                    hide_index=True,
                )

                # bar chart comparison
                fig = px.bar(df, x="商品名稱", y=["目前價格", "均價", "最低價"],
                             barmode="group", title=f"「{group['name']}」群組比價矩陣",
                             color_discrete_sequence=["#4F8EF7", "#F6AD55", "#68D391"])
                st.plotly_chart(fig, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: AI 對話
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "🤖 AI 對話":
    st.header("🤖 AI 價格分析助手")
    st.caption("基於您追蹤的商品數據，詢問任何關於價格趨勢的問題")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("例：哪個商品現在最划算？咖啡設備群組的均價趨勢如何？"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            db_context = db.get_ai_context_summary()
            response_placeholder = st.empty()
            full_response = ""
            try:
                for chunk in ai_chat.stream_response(
                    st.session_state.messages, db_context
                ):
                    full_response += chunk
                    response_placeholder.markdown(full_response + "▌")
                response_placeholder.markdown(full_response)
            except Exception as e:
                full_response = f"AI 回應失敗：{e}\n\n請確認 `.env` 中已設定 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`。"
                response_placeholder.error(full_response)

        st.session_state.messages.append({"role": "assistant", "content": full_response})
