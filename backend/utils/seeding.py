import json
import logging
from sqlmodel import Session, select
from models import Prompt, Preset

logger = logging.getLogger(__name__)

def seed_initial_data(session: Session):
    """初期データ投入 (Essentiaの特徴量を考慮した最新プリセット)"""
    
    # 1. デフォルトプロンプト
    default_prompt_content = (
        "You are a professional DJ. Create a seamless setlist from the provided tracks.\n"
        "Consider the Camelot Wheel key mixing, Energy flow, and Dynamics.\n"
        " - 'Dyn' (Loudness Range > 8dB) indicates a track with dramatic breakdowns/drops.\n"
        " - 'Flux' indicates how much the sound texture changes over time (Higher = more complex).\n"
        "Briefly explain your transition choices."
    )

    default_prompt = session.exec(select(Prompt).where(Prompt.is_default == True)).first()
    if not default_prompt:
        default_prompt = Prompt(
            name="Default Setlist Generator",
            content=default_prompt_content,
            is_default=True,
            display_order=0
        )
        session.add(default_prompt)
        session.commit()
        session.refresh(default_prompt)
    else:
        if default_prompt.content != default_prompt_content:
            default_prompt.content = default_prompt_content
            session.add(default_prompt)
            session.commit()

    # 2. 検索・雰囲気プリセット
    search_presets = [
        {
            "name": "☕️ Warmup / Lounge",
            "description": "オープニング向け。音圧変化が少なく(Low Dyn)、心地よい(Low Flux)選曲。",
            "preset_type": "search",
            "filters": {},
            "prompt_content": "Act as an opening DJ. Select deep, steady tracks that set a mood without demanding attention. Avoid big drops."
        },
        {
            "name": "💣 Peak Time Bangers",
            "description": "メインフロア直撃。高エナジー、高音圧、派手な展開。",
            "preset_type": "search",
            "filters": {},
            "prompt_content": "It is peak time. Choose the most explosive, high-energy tracks available. Focus on tracks with big build-ups."
        },
        {
            "name": "⚙️ Hypnotic / Driving",
            "description": "テクノ/ハウス向け。淡々としたグルーヴ(Low Flux)だが力強い(High Energy)。",
            "preset_type": "search",
            "filters": {},
            "prompt_content": "Create a hypnotic, driving atmosphere suitable for techno. Prioritize consistent grooves and locked-in rhythms over melodies."
        },
        {
            "name": "😭 Emotional / Anthem",
            "description": "終盤向け。ダイナミクスレンジが広く(High Dyn)、ドラマチックな展開。",
            "preset_type": "search",
            "filters": {},
            "prompt_content": "Create an emotional setlist. Look for tracks with high 'Dynamics' (Loudness Range) that indicate dramatic breakdowns and euphoric drops."
        }
    ]

    for p_data in search_presets:
        existing = session.exec(select(Preset).where(Preset.name == p_data["name"])).first()
        if not existing:
            new_prompt = Prompt(
                name=f"Preset: {p_data['name']}",
                content=p_data['prompt_content'],
                is_default=False,
                display_order=10
            )
            session.add(new_prompt)
            session.commit()
            
            preset = Preset(
                name=p_data["name"],
                description=p_data["description"],
                preset_type=p_data["preset_type"],
                filters_json=json.dumps(p_data["filters"]),
                prompt_id=new_prompt.id
            )
            session.add(preset)
            session.commit()

    # 3. セットリスト生成専用プリセット
    gen_presets = [
        {
            "name": "☀️ Melodic Day Party",
            "description": "デイパーティ用。メロディックで高揚感のあるハウス。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a setlist for a sunny outdoor Day Party / Open Air Festival.\nGenre Focus: Melodic House, Organic House, Progressive House.\nVibe: Bright, Uplifting, Emotional, Euphoric but not too aggressive.\nSelection Criteria: Choose tracks with beautiful melodies, pianos, or uplifting vocals. Avoid dark, heavy, or industrial sounds.\nFlow: Maintain a steady, happy groove. Transitions should be long and smooth."
        },
        {
            "name": "🎉 Club Anthems (Trends)",
            "description": "最新トレンド・ミーハー重視。クラブで盛り上がる選曲。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a 'Peak Time' main floor setlist focused on crowd-pleasers and current trends.\nGenre Focus: Tech House, EDM, Mainstage, Commercial Dance, Pop Remixes.\nVibe: High Energy, Party, Catchy, 'Mee-Ha' (Popular/Commercial).\nSelection Criteria: Prioritize tracks that sound like recent hits, recognizable anthems, or have big drops.\nFlow: Keep the energy very high. Quick transitions and high impact drops are preferred over smooth mixing."
        },
        {
            "name": "🎤 Hip-Hop Wordplay",
            "description": "HIPHOP重視。タイトルやリリックの関連性で繋ぐ。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a creative Hip-Hop setlist focused on 'Wordplay' and thematic transitions.\nGenre Focus: Hip-Hop, Rap, R&B, Trap.\nMixing Technique: INTELLIGENT LINKING. Try to link tracks based on their TITLES, ARTIST names, or LYRICAL themes.\nExamples: 'Money' -> 'Gold Digger', 'California Love' -> 'Hotel California' (Sample), 'Jay-Z' -> 'Beyonce'.\nFlow: Focus on the 'Conversation' between tracks rather than perfect BPM matching. Vibe compatibility is key."
        },
        {
            "name": "🎹 Harmonic Groove (Locked)",
            "description": "キーの相性最優先。グルーヴを途切れさせないTech/Deepハウス。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a 'Locked Groove' setlist for a discerning dancefloor.\nGenre Focus: Tech House, Deep Tech, Minimal.\nMixing Technique: HARMONIC MIXING IS PARAMOUNT. Every transition must be a perfect Camelot match (e.g. 5A -> 5A or 5A -> 4A).\nVibe: Hypnotic, consistent, rolling basslines.\nFlow: Do not break the groove. Avoid long breakdowns or silence. Keep the beat going continuously."
        },
        {
            "name": "🏎️ Night Drive",
            "description": "深夜のドライブ。疾走感のあるプログレッシブ/シンセウェーブ。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a cinematic setlist suitable for a late-night drive on the highway.\nGenre Focus: Progressive House, Melodic Techno, Synthwave.\nVibe: Immersive, Driving, Cool, Neon, Cyberpunk.\nSelection Criteria: Choose tracks with consistent driving beats, arpeggiated synths, and atmospheric pads.\nFlow: Create a continuous, trance-like journey. Avoid sudden energy drops."
        },
        {
            "name": "🍸 Lounge / Sunset",
            "description": "夕暮れやラウンジ向け。チルで洗練された選曲。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a sophisticated background setlist for a Sunset Lounge or luxury bar.\nGenre Focus: Deep House, Lo-Fi House, Downtempo, Chillout, Organic.\nVibe: Relaxed, Classy, Warm, Jazzy.\nSelection Criteria: Avoid aggressive drums or harsh synths. Prioritize smooth basslines, saxophone, piano, and soft vocals.\nFlow: Gentle waves of energy. Never too loud or obtrusive."
        },
        {
            "name": "⚡️ Quick Mixing / Mashup",
            "description": "高回転ミックス。ジャンルを横断して盛り上げる。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a high-paced, 'Quick Mix' style setlist.\nStyle: Open Format / Mashup style.\nVibe: Urgent, Exciting, Unpredictable.\nMixing Technique: Switch tracks quickly to keep the audience engaged. Prioritize tracks with recognizable hooks or heavy drops.\nFlow: Constant energy spikes. It's okay to jump genres if the BPM allows."
        },
        {
            "name": "📉 Deep & Hypnotic",
            "description": "アフターアワーズ。深く、没入感のあるミニマル。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a setlist for an 'Afterhours' dark room session.\nGenre Focus: Minimal Techno, Dub Techno, Deep House, Rominimal.\nVibe: Dark, Trippy, Sub-heavy, Repetitive, Mental.\nSelection Criteria: Focus on tracks with subtle changes and deep sub-bass. Low brightness/treble.\nFlow: Very slow progression. The goal is to put the listener in a trance state."
        },
        {
            "name": "🏋️ Workout / Gym",
            "description": "ジム・ワークアウト用。高BPMでモチベーション維持。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a motivational setlist for a high-intensity workout.\nGenre Focus: EDM, Hardstyle, Drum & Bass, Techno.\nVibe: Aggressive, Powerful, Fast, Relentless.\nSelection Criteria: Tracks with driving beats and powerful drops. No slow intros.\nFlow: Keep the tempo high and consistent to match running or lifting pace."
        },
        {
            "name": "🏖️ Beach Bar",
            "description": "ビーチサイド。トロピカルでリズミカルな選曲。",
            "preset_type": "generation",
            "filters": {},
            "prompt_content": "Create a setlist for a laid-back Beach Bar.\nGenre Focus: Tropical House, Reggaeton, Latin House, Afro House.\nVibe: Sunny, Fun, Rhythmic, Sexy.\nSelection Criteria: Percussion-heavy tracks, Spanish vocals, steel drums, or marimbas.\nFlow: Fun and inviting. Makes people want to sway with a drink in hand."
        }
    ]

    for p_data in gen_presets:
        existing = session.exec(select(Preset).where(Preset.name == p_data["name"])).first()
        if not existing:
            new_prompt = Prompt(
                name=f"GenPreset: {p_data['name']}",
                content=p_data['prompt_content'],
                is_default=False,
                display_order=20
            )
            session.add(new_prompt)
            session.commit()
            
            preset = Preset(
                name=p_data["name"],
                description=p_data["description"],
                preset_type=p_data["preset_type"],
                filters_json=json.dumps(p_data["filters"]),
                prompt_id=new_prompt.id
            )
            session.add(preset)
            session.commit()
