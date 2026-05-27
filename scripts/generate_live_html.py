#!/usr/bin/env python3
"""Interactive HTML debate canvas generator for TradingAgents."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("html_generator")

SPEAKER_CONFIGS = {
    "sentiment analyst": {
        "name_cn": "情绪分析师",
        "avatar": "🎭",
        "color": "#a855f7",
        "align": "left",
        "team": "analyst",
    },
    "market analyst": {
        "name_cn": "技术分析师",
        "avatar": "📈",
        "color": "#06b6d4",
        "align": "left",
        "team": "analyst",
    },
    "news analyst": {
        "name_cn": "新闻分析师",
        "avatar": "📰",
        "color": "#3b82f6",
        "align": "left",
        "team": "analyst",
    },
    "fundamentals analyst": {
        "name_cn": "基本面分析师",
        "avatar": "📊",
        "color": "#ec4899",
        "align": "left",
        "team": "analyst",
    },
    "bull researcher": {
        "name_cn": "多头研究员",
        "avatar": "🐂",
        "color": "#ef4444",
        "align": "left",
        "team": "research",
    },
    "bear researcher": {
        "name_cn": "空头研究员",
        "avatar": "🐻",
        "color": "#10b981",
        "align": "right",
        "team": "research",
    },
    "research manager": {
        "name_cn": "研究主管",
        "avatar": "👑",
        "color": "#f59e0b",
        "align": "center",
        "team": "research",
    },
    "trader": {
        "name_cn": "交易员",
        "avatar": "⚡",
        "color": "#8b5cf6",
        "align": "left",
        "team": "trading",
    },
    "aggressive analyst": {
        "name_cn": "激进风控",
        "avatar": "🦁",
        "color": "#f43f5e",
        "align": "left",
        "team": "risk",
    },
    "conservative analyst": {
        "name_cn": "保守风控",
        "avatar": "🛡️",
        "color": "#475569",
        "align": "right",
        "team": "risk",
    },
    "neutral analyst": {
        "name_cn": "中立风控",
        "avatar": "⚖️",
        "color": "#64748b",
        "align": "left",
        "team": "risk",
    },
    "portfolio manager": {
        "name_cn": "投资组合经理 (PM)",
        "avatar": "🏆",
        "color": "#f97316",
        "align": "center",
        "team": "risk",
    }
}


def get_speaker_config(speaker: str) -> Dict[str, Any]:
    key = speaker.lower().replace(" researcher", " researcher").replace(" analyst", " analyst").strip()
    
    if "bull" in key:
        key = "bull researcher"
    elif "bear" in key:
        key = "bear researcher"
    elif "manager" in key or "pm" in key:
        if "portfolio" in key:
            key = "portfolio manager"
        else:
            key = "research manager"
    elif "aggressive" in key:
        key = "aggressive analyst"
    elif "conservative" in key:
        key = "conservative analyst"
    elif "neutral" in key:
        key = "neutral analyst"
    elif "trader" in key:
        key = "trader"
    elif "sentiment" in key:
        key = "sentiment analyst"
    elif "market" in key:
        key = "market analyst"
    elif "news" in key:
        key = "news analyst"
    elif "fundamental" in key:
        key = "fundamentals analyst"
        
    return SPEAKER_CONFIGS.get(key, {
        "name_cn": speaker,
        "avatar": "👤",
        "color": "#94a3b8",
        "align": "left",
        "team": "unknown"
    })


def parse_markdown_debate(md_text: str) -> List[Dict[str, Any]]:
    """Parse dialogue segments from the markdown file."""
    pattern = re.compile(r'^###\s+([^\n]+)', re.MULTILINE)
    matches = list(pattern.finditer(md_text))
    
    messages = []
    for i, match in enumerate(matches):
        speaker = match.group(1).strip()
        start = match.end()
        
        # Find next heading (level 2 or level 3)
        end = len(md_text)
        next_heading = re.search(r'^(##|###)\s', md_text[start:], re.MULTILINE)
        if next_heading:
            end = start + next_heading.start()
            
        content = md_text[start:end].strip()
        if not content:
            continue
            
        # Clean speaker names from markdown styles
        speaker = re.sub(r'[*_`]', '', speaker).strip()
        config = get_speaker_config(speaker)
        
        messages.append({
            "speaker": speaker,
            "name_cn": config["name_cn"],
            "avatar": config["avatar"],
            "color": config["color"],
            "align": config["align"],
            "team": config["team"],
            "content": content
        })
    return messages


def extract_meta(md_text: str) -> Dict[str, str]:
    """Extract metadata (title, ticker, date, final rating) from the report."""
    meta = {
        "title": "TradingAgents 智能体投研辩论",
        "ticker": "Unknown",
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "rating": "Hold",
    }
    
    # Try to extract from first line title
    title_match = re.search(r'^#\s+([^\n]+)', md_text)
    if title_match:
        raw_title = title_match.group(1).replace("交易分析报告", "").strip()
        meta["title"] = raw_title
        
    ticker_match = re.search(r'标的:\s*([a-zA-Z0-9.]+)', md_text, re.IGNORECASE)
    if ticker_match:
        meta["ticker"] = ticker_match.group(1).upper()
        
    date_match = re.search(r'交易日:\s*([0-9-]+)', md_text, re.IGNORECASE)
    if date_match:
        meta["date"] = date_match.group(1)
        
    # Extract final decision rating
    rating_patterns = [
        r'Rating:\s*(Buy|Overweight|Hold|Underweight|Sell)',
        r'评级：\s*(Buy|Overweight|Hold|Underweight|Sell)',
        r'智能体评级:\s*\*\*(Buy|Overweight|Hold|Underweight|Sell)\*\*',
        r'\*\*Rating\*\*:\s*(Buy|Overweight|Hold|Underweight|Sell)',
        r'【(Buy|Overweight|Hold|Underweight|Sell)】',
        r'综合投资决策：.*(Buy|Overweight|Hold|Underweight|Sell)',
    ]
    for pattern in rating_patterns:
        match = re.search(pattern, md_text, re.IGNORECASE)
        if match:
            meta["rating"] = match.group(1).capitalize()
            break
            
    return meta


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} ({ticker}) - Multi-Agent Debate Live Room</title>
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Marked Markdown Parser -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
        body {{
            font-family: 'Noto Sans SC', 'JetBrains Mono', sans-serif;
            background-color: #0f172a;
            color: #e2e8f0;
        }}
        .chat-container {{
            background-image: radial-gradient(#1e293b 1px, transparent 1px);
            background-size: 16px 16px;
        }}
        /* Customize marked markdown elements */
        .markdown-content p {{
            margin-bottom: 0.75rem;
            line-height: 1.6;
        }}
        .markdown-content p:last-child {{
            margin-bottom: 0;
        }}
        .markdown-content ul, .markdown-content ol {{
            margin-left: 1.25rem;
            margin-bottom: 0.75rem;
            list-style-type: disc;
        }}
        .markdown-content table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 0.75rem;
            font-size: 0.875rem;
        }}
        .markdown-content th, .markdown-content td {{
            border: 1px solid #334155;
            padding: 0.5rem;
            text-align: left;
        }}
        .markdown-content th {{
            background-color: #1e293b;
        }}
        .markdown-content blockquote {{
            border-left: 4px solid #475569;
            padding-left: 0.75rem;
            color: #94a3b8;
            margin-bottom: 0.75rem;
            font-style: italic;
        }}
        /* Animation fade-in */
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .message-bubble {{
            animation: fadeIn 0.4s ease forwards;
        }}
        /* Custom scrollbar */
        ::-webkit-scrollbar {{
            width: 6px;
        }}
        ::-webkit-scrollbar-track {{
            background: #0f172a;
        }}
        ::-webkit-scrollbar-thumb {{
            background: #334155;
            border-radius: 3px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: #475569;
        }}
    </style>
</head>
<body class="h-screen flex flex-col overflow-hidden">

    <!-- Top Header -->
    <header class="bg-slate-900 border-b border-slate-800 px-6 py-4 flex justify-between items-center z-10 shrink-0">
        <div class="flex items-center space-x-3">
            <span class="text-2xl">🤖</span>
            <div>
                <h1 class="text-lg font-bold text-white flex items-center space-x-2">
                    <span>{title}</span>
                    <span class="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded font-mono">{ticker}</span>
                </h1>
                <p class="text-xs text-slate-400">TradingAgents 多智能体投研唇枪舌战直播间</p>
            </div>
        </div>
        <div class="flex items-center space-x-4">
            <div class="text-right">
                <p class="text-xs text-slate-400">交易分析日</p>
                <p class="text-sm font-bold text-indigo-400 font-mono">{date}</p>
            </div>
            <div class="h-8 w-px bg-slate-800"></div>
            <div>
                <span id="rating-badge" class="px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                    {rating}
                </span>
            </div>
        </div>
    </header>

    <!-- Main Workspace -->
    <div class="flex-1 flex overflow-hidden">
        
        <!-- Left Sidebar (Control Dashboard) -->
        <aside class="w-80 bg-slate-900 border-r border-slate-800 p-6 flex flex-col justify-between shrink-0 overflow-y-auto">
            <div class="space-y-6">
                <!-- Live Summary Card -->
                <div class="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 space-y-3">
                    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">🌟 辩论看点与进度</h3>
                    <p class="text-sm text-slate-300 leading-relaxed">
                        本页面由 TradingAgents 自动生成。它完整解析了投研团队（多头牛派、空头熊派、风险管控团队与组合经理）多轮唇枪舌战的历史流。点击右侧<b>「自动播放」</b>，可沉浸式还原当时的激烈辩论实况。
                    </p>
                </div>

                <!-- Autoplay Controls -->
                <div class="space-y-3">
                    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">🕹️ 播放控制盘</h3>
                    <div class="grid grid-cols-2 gap-2">
                        <button id="btn-play" class="flex items-center justify-center space-x-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white text-sm py-2 px-4 rounded-lg font-medium transition duration-200">
                            <span id="play-icon">▶</span> <span id="play-text">自动播放</span>
                        </button>
                        <button id="btn-reset" class="flex items-center justify-center space-x-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm py-2 px-4 rounded-lg font-medium border border-slate-700 transition duration-200">
                            <span>🔄</span> <span>重置视图</span>
                        </button>
                    </div>
                    
                    <!-- Speed slider -->
                    <div class="space-y-1.5 pt-2">
                        <div class="flex justify-between text-xs text-slate-400 font-mono">
                            <span>发言间隔速度</span>
                            <span id="speed-val">1.5s</span>
                        </div>
                        <input id="speed-slider" type="range" min="500" max="4000" step="250" value="1500" class="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500">
                    </div>
                </div>

                <!-- Filters -->
                <div class="space-y-3">
                    <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">🎭 环节过滤</h3>
                    <div class="flex flex-col space-y-1.5" id="filter-group">
                        <button class="filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium transition bg-indigo-500/10 text-indigo-400 border border-indigo-500/20" data-filter="all">
                            🌐 全面研判总流程
                        </button>
                        <button class="filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition" data-filter="analyst">
                            📊 Step 1: 分析师团队情报 (Analysts)
                        </button>
                        <button class="filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition" data-filter="research">
                            🐂 Step 2: 多空大辩论 (Research Team)
                        </button>
                        <button class="filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition" data-filter="trading">
                            ⚡ Step 3: 交易执行计划 (Trader)
                        </button>
                        <button class="filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition" data-filter="risk">
                            🛡️ Step 4: 风控合规审判 (Portfolio Manager)
                        </button>
                    </div>
                </div>
            </div>

            <!-- Footer info -->
            <div class="border-t border-slate-800 pt-4 text-[10px] text-slate-500 space-y-1 font-mono">
                <p>Framework: TradingAgents v0.3</p>
                <p>HTML Engine: Live Debate Canvas</p>
                <p>Status: Local SQLite Connected</p>
            </div>
        </aside>

        <!-- Right Chat Stage -->
        <main class="flex-1 flex flex-col bg-slate-950 overflow-hidden relative">
            <!-- Grid Background Chat Container -->
            <div id="chat-stage" class="chat-container flex-1 overflow-y-auto p-6 space-y-6">
                <!-- Dynamic messages go here -->
            </div>
            
            <!-- Autoscroll Indicator/Banner -->
            <div id="scrolling-indicator" class="hidden absolute bottom-4 right-6 bg-slate-800/80 backdrop-blur text-indigo-400 px-3 py-1.5 rounded-full text-xs font-medium border border-slate-700 shadow-lg pointer-events-none">
                ⬇ 正在跟随发言流...
            </div>
        </main>

    </div>

    <!-- Data Injection -->
    <script>
        let messageData = [];
        let rating = "HOLD";
        let title = "{title}";
        let ticker = "{ticker}";
        let date = "{date}";

        // Render controller variables
        let isPlaying = false;
        let playIndex = 0;
        let timer = null;
        let currentFilter = "all";
        
        // Filter elements
        const filterButtons = document.querySelectorAll('.filter-btn');
        const chatStage = document.getElementById('chat-stage');
        const btnPlay = document.getElementById('btn-play');
        const playIcon = document.getElementById('play-icon');
        const playText = document.getElementById('play-text');
        const btnReset = document.getElementById('btn-reset');
        const speedSlider = document.getElementById('speed-slider');
        const speedVal = document.getElementById('speed-val');
        const scrollIndicator = document.getElementById('scrolling-indicator');

        // Check for dynamic URL query params
        const urlParams = new URLSearchParams(window.location.search);
        const paramTicker = urlParams.get('ticker');
        const paramDate = urlParams.get('date');

        async function initDebateRoom() {{
            if (paramTicker && paramDate) {{
                // Dynamic Mode: fetch from local API server
                try {{
                    const res = await fetch(`/api/report?ticker=${{encodeURIComponent(paramTicker)}}&date=${{encodeURIComponent(paramDate)}}`);
                    if (!res.ok) {{
                        throw new Error(`API returned status ${{res.status}}`);
                    }}
                    const data = await res.json();
                    if (!data.ok) {{
                        throw new Error(data.error || "Failed to load report data");
                    }}
                    
                    messageData = data.messages;
                    rating = (data.rating || "HOLD").trim().toUpperCase();
                    title = data.title || "TradingAgents 智能体投研辩论";
                    ticker = data.ticker || paramTicker.toUpperCase();
                    date = data.date || paramDate;
                    
                    // Update DOM elements
                    document.title = `${{title}} (${{ticker}}) - Multi-Agent Debate Live Room`;
                    document.querySelector('header h1 span:first-child').textContent = title;
                    document.querySelector('header h1 span:last-child').textContent = ticker;
                    document.querySelector('header p.text-indigo-400').textContent = date;
                }} catch (e) {{
                    console.error("Dynamic fetch failed:", e);
                    chatStage.innerHTML = `<div class="text-center text-red-400 py-12">❌ 加载动态数据失败: ${{e.message}}</div>`;
                    return;
                }}
            }} else {{
                // Static Fallback Mode: use hardcoded injected data
                try {{
                    messageData = {messages_json};
                    rating = "{rating}".trim().toUpperCase();
                }} catch (err) {{
                    console.error("Static data load failed:", err);
                }}
            }}

            // Style rating badge
            const badge = document.getElementById('rating-badge');
            badge.textContent = rating;
            if (["BUY", "OVERWEIGHT"].includes(rating)) {{
                badge.className = "px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider bg-rose-500/10 text-rose-400 border border-rose-500/20";
            }} else if (["SELL", "UNDERWEIGHT"].includes(rating)) {{
                badge.className = "px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
            }} else {{
                badge.className = "px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider bg-amber-500/10 text-amber-400 border border-amber-500/20";
            }}

            resetPlayback();
        }}

        // Marked rendering options
        marked.setOptions({{
            gfm: true,
            breaks: true,
            sanitize: false
        }});

        // Render single message node
        function createMessageNode(msg) {{
            const div = document.createElement('div');
            
            // Align style
            let alignClass = "justify-start";
            let bubbleBg = "bg-slate-800 text-slate-200 border border-slate-700/50 rounded-br-2xl";
            let avatarOrder = "order-1";
            let contentOrder = "order-2";
            let alignmentText = "text-left";
            
            if (msg.align === "right") {{
                alignClass = "justify-end";
                bubbleBg = "bg-indigo-950/40 text-slate-200 border border-indigo-500/20 rounded-bl-2xl";
                avatarOrder = "order-2";
                contentOrder = "order-1";
                alignmentText = "text-right";
            }} else if (msg.align === "center") {{
                alignClass = "justify-center";
                bubbleBg = "bg-slate-900 border-2 border-amber-500/30 text-amber-100 rounded-2xl max-w-4xl shadow-lg";
                avatarOrder = "hidden";
                contentOrder = "order-1";
                alignmentText = "text-center";
            }}

            div.className = `flex ${{alignClass}} items-start space-x-3 max-w-full message-bubble`;
            
            const htmlContent = marked.parse(msg.content);
            const titleColor = msg.color;

            div.innerHTML = `
                <!-- Avatar -->
                <div class="${avatarOrder} w-10 h-10 rounded-full flex items-center justify-center text-xl shadow-md border shrink-0" style="border-color: ${titleColor}; background-color: ${titleColor}20">
                    ${{msg.avatar}}
                </div>
                
                <!-- Content Bubble -->
                <div class="${contentOrder} max-w-[75%] space-y-1">
                    <div class="flex items-center space-x-2 ${msg.align === 'right' ? 'justify-end' : ''}">
                        <span class="text-xs font-bold" style="color: ${titleColor}">${{msg.name_cn}}</span>
                        <span class="text-[10px] bg-slate-900 text-slate-400 px-1.5 py-0.5 rounded font-mono uppercase tracking-wider">${{msg.speaker}}</span>
                    </div>
                    <div class="px-4 py-3 rounded-t-2xl shadow-md ${bubbleBg}">
                        <div class="markdown-content text-sm leading-relaxed" style="text-align: left;">
                            ${{htmlContent}}
                        </div>
                    </div>
                </div>
            `;
            return div;
        }}

        // Populate instantly
        function instantRenderAll() {{
            chatStage.innerHTML = '';
            const filtered = getFilteredMessages();
            filtered.forEach(msg => {{
                chatStage.appendChild(createMessageNode(msg));
            }});
            chatStage.scrollTop = chatStage.scrollHeight;
        }}

        function getFilteredMessages() {{
            if (currentFilter === "all") return messageData;
            return messageData.filter(msg => msg.team === currentFilter);
        }}

        // Dynamic playback routine
        function playNext() {{
            const filtered = getFilteredMessages();
            if (playIndex >= filtered.length) {{
                pausePlayback();
                return;
            }}

            const msg = filtered[playIndex];
            const node = createMessageNode(msg);
            chatStage.appendChild(node);
            
            // Auto scroll down smoothly
            chatStage.scrollTo({{
                top: chatStage.scrollHeight,
                behavior: 'smooth'
            }});
            
            playIndex++;
            
            // Set next timer
            timer = setTimeout(playNext, parseInt(speedSlider.value));
        }}

        function startPlayback() {{
            if (playIndex === 0) {{
                chatStage.innerHTML = '';
            }}
            isPlaying = true;
            playIcon.textContent = "⏸";
            playText.textContent = "暂停播放";
            scrollIndicator.classList.remove('hidden');
            playNext();
        }}

        function pausePlayback() {{
            isPlaying = false;
            playIcon.textContent = "▶";
            playText.textContent = "自动播放";
            scrollIndicator.classList.add('hidden');
            if (timer) clearTimeout(timer);
        }}

        function resetPlayback() {{
            pausePlayback();
            playIndex = 0;
            instantRenderAll();
        }}

        // Event Bindings
        btnPlay.addEventListener('click', () => {{
            if (isPlaying) {{
                pausePlayback();
            }} else {{
                startPlayback();
            }}
        }});

        btnReset.addEventListener('click', () => {{
            resetPlayback();
        }});

        speedSlider.addEventListener('input', () => {{
            speedVal.textContent = (speedSlider.value / 1000).toFixed(1) + 's';
        }});

        // Filter clicks
        filterButtons.forEach(btn => {{
            btn.addEventListener('click', () => {{
                // Toggle active style
                filterButtons.forEach(b => {{
                    b.className = "filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition";
                }});
                btn.className = "filter-btn text-left text-xs py-2 px-3 rounded-lg font-medium transition bg-indigo-500/10 text-indigo-400 border border-indigo-500/20";
                
                currentFilter = btn.dataset.filter;
                resetPlayback();
            }});
        }});

        // Initial render
        initDebateRoom();
    </script>
</body>
</html>
"""


def generate_live_html(complete_report_path: str | Path, output_html_path: str | Path) -> bool:
    """Generate WeChat/Discord-style Interactive HTML Debate Canvas from complete_report.md."""
    try:
        report_path = Path(complete_report_path)
        if not report_path.is_file():
            logger.error(f"Report file not found: {complete_report_path}")
            return False
            
        md_text = report_path.read_text(encoding="utf-8")
        
        # 1. Extract metadata
        meta = extract_meta(md_text)
        
        # 2. Parse dialogue messages
        messages = parse_markdown_debate(md_text)
        if not messages:
            logger.warning(f"No dialogue segments parsed from {complete_report_path}")
            return False
            
        # 3. Inject JSON and compile template
        messages_json = json.dumps(messages, ensure_ascii=False, indent=2)
        html_content = HTML_TEMPLATE.format(
            title=meta["title"],
            ticker=meta["ticker"],
            date=meta["date"],
            rating=meta["rating"],
            messages_json=messages_json
        )
        
        # 4. Write output file
        out_path = Path(output_html_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_content, encoding="utf-8")
        logger.info(f"Successfully generated interactive debate HTML at: {out_path.resolve()}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to generate interactive HTML canvas: {e}", exc_info=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an interactive single-file HTML live debate room from complete_report.md")
    parser.add_argument(
        "--report",
        required=True,
        help="Path to complete_report.md file"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output debate_live.html file"
    )
    args = parser.parse_args()
    
    ok = generate_live_html(args.report, args.output)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
