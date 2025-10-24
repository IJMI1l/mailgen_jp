import streamlit as st
import google.generativeai as genai
import json
import re
import os
from dotenv import load_dotenv
from typing import Tuple, List, Dict

# .envからAPIキーを読み込み
load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not GOOGLE_API_KEY:
    st.error("環境変数 GEMINI_API_KEY が設定されていません。.env ファイルを確認してください。")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-exp')


def rule_based_check(mail_text: str, is_internal: bool) -> List[str]:
    """ルールベースでメール本文をチェック"""
    issues = []
    
    # 宛名チェック
    if is_internal:
        # 社内は「さん」または「様」
        if not re.search(r"(さん|様)", mail_text):
            issues.append("社内メールでは「さん」または「様」を使用してください。")
    else:
        # 社外は「様」「殿」「御中」
        if not re.search(r"(様|殿|御中)", mail_text):
            issues.append("社外メールでは適切な敬称(様/殿/御中)を使用してください。")
    
    # 結びの挨拶チェック
    closing_phrases = ["よろしくお願いいたします", "よろしくお願い申し上げます", "何卒よろしくお願いいたします", "よろしくお願いします"]
    if not any(phrase in mail_text for phrase in closing_phrases):
        issues.append("結びの挨拶が不足しています。")
    
    return issues


def format_sender_signature(sender: Dict[str, str]) -> str:
    """送信者の署名をフォーマット"""
    lines = []
    lines.append("=" * 40)
    
    if sender.get('company'):
        lines.append(sender['company'])
    if sender.get('department'):
        lines.append(sender['department'])
    if sender.get('position') and sender.get('last_name') and sender.get('first_name'):
        lines.append(f"{sender['position']} {sender['last_name']} {sender['first_name']}")
    elif sender.get('last_name') and sender.get('first_name'):
        lines.append(f"{sender['last_name']} {sender['first_name']}")
    elif sender.get('position'):
        lines.append(sender['position'])
    
    # 連絡先情報
    contact_info = []
    if sender.get('email'):
        contact_info.append(f"Email: {sender['email']}")
    if sender.get('phone'):
        contact_info.append(f"TEL: {sender['phone']}")
    if sender.get('mobile'):
        contact_info.append(f"携帯: {sender['mobile']}")
    
    if contact_info:
        lines.extend(contact_info)
    
    lines.append("=" * 40)
    
    return '\n'.join(lines)


def get_recipient_display_name(recipient: Dict[str, str], is_internal: bool) -> str:
    """受信者の表示名を取得"""
    if not recipient.get('last_name') and not recipient.get('first_name'):
        return "[宛先名]"
    
    last_name = recipient.get('last_name', '')
    first_name = recipient.get('first_name', '')
    
    if is_internal:
        # 社内: 苗字のみ + さん（またはフルネーム + さん、役職による）
        if recipient.get('position') and recipient.get('position') in ['社長', '部長', '課長', '係長']:
            # 役職が高い場合はフルネーム
            return f"{last_name} {first_name}" if first_name else last_name
        else:
            # 通常は苗字のみ
            return last_name if last_name else first_name
    else:
        # 社外: フルネーム
        return f"{last_name} {first_name}" if first_name else last_name


def create_prompt(
    content: str,
    relationship: str,
    purpose: str,
    sender: Dict[str, str],
    recipient: Dict[str, str],
    is_internal: bool,
    issues: List[str] = None
) -> str:
    """プロンプト生成"""
    
    sender_signature = format_sender_signature(sender)
    recipient_display = get_recipient_display_name(recipient, is_internal)
    
    # 社内外の区分に応じた指示
    if is_internal:
        tone_instruction = """
【社内メールの注意点】
- 敬語は丁寧語中心で、過度に堅苦しくしない
- 宛名は「○○さん」または「○○様」（役職が高い場合は「○○部長」など役職名も可）
- 時候の挨拶は不要（「お疲れ様です」程度で可）
- 結びは「よろしくお願いします」など、やや簡潔に
- 署名は簡潔に（部署名と名前、内線番号など）
"""
    else:
        tone_instruction = """
【社外メールの注意点】
- 丁寧な敬語を使用（謙譲語・尊敬語を適切に）
- 宛名は「○○様」（会社・部署宛の場合は「御中」）
- 時候の挨拶を含める（季節に応じた挨拶）
- 結びは「何卒よろしくお願いいたします」など、丁寧に
- 署名は詳細に（会社名、部署、役職、名前、連絡先）
"""
    
    # 受信者情報の整理
    recipient_info_parts = []
    if recipient.get('company'):
        recipient_info_parts.append(f"会社: {recipient['company']}")
    if recipient.get('department'):
        recipient_info_parts.append(f"部署: {recipient['department']}")
    if recipient.get('position'):
        recipient_info_parts.append(f"役職: {recipient['position']}")
    recipient_info_parts.append(f"名前: {recipient_display}")
    
    recipient_info = '\n'.join(recipient_info_parts)
    
    base_prompt = f"""あなたは日本のビジネスメールの専門家です。
以下の内容を、日本のビジネスメールの作法に従って適切な形式に変換してください。

【メールの種類】
{"社内メール" if is_internal else "社外メール"}

{tone_instruction}

【受信者情報】
{recipient_info}

【送信者署名（メール末尾に使用）】
{sender_signature}

【入力内容】
{content}

【相手との関係】
{relationship}

【メールの目的】
{purpose}

以下の点に注意して変換してください:
1. {"社内" if is_internal else "社外"}メールとして適切なトーンと敬語レベル
2. ビジネスメールの基本的な構成(挨拶、本文、結び、署名)
3. {"時候の挨拶は不要で「お疲れ様です」程度で開始" if is_internal else "時候の挨拶(現在の季節に応じた)を含める"}
4. 適切な件名
5. 宛名には受信者情報を使用し、{"「さん」または役職名を使用" if is_internal else "「様」「殿」「御中」を適切に使用"}
6. 結びには{"「よろしくお願いします」" if is_internal else "「よろしくお願いいたします」"}などの挨拶を含める
7. 署名欄には上記の送信者署名をそのまま使用する
8. 文章は自然で読みやすく、ビジネスにふさわしい表現を使用する
9. 日本語で出力する。（外国語の名詞や専門用語などは構いません）
10.送信者や宛名の参照できない情報は○○を書く。
11. 不明確な点は推測せず、一般的な表現を使用する。
12.現在の日付や季節に応じた表現を使用する。

出力形式:
{{
    "subject": "件名",
    "body": "本文（宛名から署名まで完全な形式）"
}}

必ずJSONフォーマットで出力してください。コードブロックは使用せず、純粋なJSON文字列のみを返してください。"""

    if issues:
        base_prompt += "\n\n【重要】前回の出力に以下の問題が見つかりました。必ず修正してください:\n"
        base_prompt += "\n".join(f"- {issue}" for issue in issues)
    
    return base_prompt


def safe_json_parse(text: str) -> dict:
    """JSONを安全にパース"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                raise ValueError("JSONのパースに失敗しました")
        else:
            raise ValueError("有効なJSONが見つかりませんでした")


def format_email(
    content: str,
    relationship: str,
    purpose: str,
    sender: Dict[str, str],
    recipient: Dict[str, str],
    is_internal: bool,
    max_retries: int = 2
) -> Tuple[str, str, List[str]]:
    """メール生成（リトライ機能付き）"""
    issues = []
    
    for attempt in range(max_retries + 1):
        try:
            prompt = create_prompt(content, relationship, purpose, sender, recipient, is_internal, issues if attempt > 0 else None)
            response = model.generate_content(prompt)
            
            if not response.text:
                raise ValueError("APIからのレスポンスが空です")
            
            result = safe_json_parse(response.text)
            
            if "subject" not in result or "body" not in result:
                raise ValueError("レスポンスに必須フィールド（subject, body）が含まれていません")
            
            issues = rule_based_check(result["body"], is_internal)
            
            if not issues:
                return result["subject"], result["body"], []
            
            if attempt == max_retries:
                return result["subject"], result["body"], issues
                
        except Exception as e:
            if attempt == max_retries:
                return "エラーが発生しました", f"メール生成中にエラーが発生しました。\n\nエラー内容: {str(e)}", [str(e)]
            continue
    
    return "エラーが発生しました", "メール生成に失敗しました", ["リトライ回数を超過しました"]


# Streamlit UI
st.set_page_config(
    page_title="ビジネスメール作成機", 
    page_icon="📧", 
    layout="wide",
    initial_sidebar_state="collapsed"  # モバイルではサイドバーを初期状態で閉じる
)

# モバイル対応のCSS
st.markdown("""
<style>
    /* モバイル対応 */
    @media (max-width: 768px) {
        .stTextInput, .stTextArea {
            font-size: 16px !important; /* iOSのズーム防止 */
        }
        
        .main .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            max-width: 100% !important;
        }
        
        /* サイドバーをモバイルで使いやすく */
        section[data-testid="stSidebar"] {
            width: 100% !important;
            max-width: 100% !important;
        }
        
        /* ボタンを大きく */
        .stButton button {
            width: 100% !important;
            padding: 0.75rem !important;
            font-size: 1rem !important;
        }
    }
    
    /* タブレット対応 */
    @media (max-width: 1024px) {
        .main .block-container {
            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }
    }
    
    /* コードブロックのスクロール */
    .stCodeBlock {
        overflow-x: auto !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("📧 ビジネスメール作成機")
st.caption("AIがあなたの要点から、社内・社外に適したビジネスメールを自動生成します。")
st.markdown("---")

# サイドバー: 送信者・受信者情報
with st.sidebar:
    col_header1, col_button1 = st.columns([3, 1])
    with col_header1:
        st.header("👤 送信者情報（あなた）")
    with col_button1:
        st.write("")
        if st.button("🔄", key="reset_sender_btn", help="送信者情報をリセット"):
            reset_sender()
            st.rerun()
    
    sender_company = st.text_input("会社名", key="sender_company", placeholder="例: 株式会社〇〇")
    sender_department = st.text_input("部署名", key="sender_department", placeholder="例: 営業部")
    sender_position = st.text_input("役職", key="sender_position", placeholder="例: 課長")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        sender_last_name = st.text_input("姓", key="sender_last_name", placeholder="例: 山田")
    with col_s2:
        sender_first_name = st.text_input("名", key="sender_first_name", placeholder="例: 太郎")
    
    st.subheader("📞 連絡先")
    sender_email = st.text_input("メールアドレス", key="sender_email", placeholder="例: yamada@example.com")
    sender_phone = st.text_input("電話番号", key="sender_phone", placeholder="例: 03-1234-5678")
    sender_mobile = st.text_input("携帯電話", key="sender_mobile", placeholder="例: 090-1234-5678")
    
    st.markdown("---")
    
    col_header2, col_button2 = st.columns([3, 1])
    with col_header2:
        st.header("📬 宛先情報")
    with col_button2:
        st.write("")
        if st.button("🔄", key="reset_recipient_btn", help="宛先情報をリセット"):
            reset_recipient()
            st.rerun()
    
    # 社内外の区分
    is_internal = st.radio(
        "メールの種類",
        options=[False, True],
        format_func=lambda x: "🏢 社内メール" if x else "🌐 社外メール",
        help="社内メールと社外メールで敬語のレベルや形式が変わります"
    )
    
    if not is_internal:
        recipient_company = st.text_input("会社名", key="recipient_company", placeholder="例: 株式会社△△")
    else:
        recipient_company = sender_company  # 社内なら送信者と同じ会社
    
    recipient_department = st.text_input("部署名", key="recipient_department", placeholder="例: 総務部")
    recipient_position = st.text_input("役職", key="recipient_position", placeholder="例: 部長")
    
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        recipient_last_name = st.text_input("姓", key="recipient_last_name", placeholder="例: 佐藤")
    with col_r2:
        recipient_first_name = st.text_input("名", key="recipient_first_name", placeholder="例: 花子")
    
    st.markdown("---")
    st.caption("💡 未入力の項目は自動的に補完されます")

# メインコンテンツ
# モバイル対応：画面幅に応じてレイアウトを変更
is_mobile = st.session_state.get('is_mobile', False)

# モバイル判定用のJavaScript（簡易版）
st.markdown("""
<script>
    // モバイル判定（画面幅768px以下）
    if (window.innerWidth <= 768) {
        window.parent.postMessage({type: 'streamlit:setComponentValue', value: true}, '*');
    }
</script>
""", unsafe_allow_html=True)

# レスポンシブなカラムレイアウト
if st.session_state.get('mobile_mode', False):
    # モバイル：1カラム
    col1 = st.container()
    col2 = st.container()
else:
    # デスクトップ：2カラム
    col1, col2 = st.columns(2)

with col1:
    st.subheader("📝 メール情報")
    relationship = st.text_input(
        "相手との関係",
        placeholder="例: 直属の上司、他部署の同僚、取引先、初めての連絡先など",
        help="相手との関係性を入力すると、適切な敬語レベルが選択されます"
    )
    purpose = st.text_input(
        "メールの目的",
        placeholder="例: 報告、依頼、お詫び、お礼、問い合わせなど",
        help="メールの目的を明確にすることで、適切な文面が生成されます"
    )
    content = st.text_area(
        "メール内容（要点）",
        height=250,
        placeholder="伝えたい内容を箇条書きや簡潔な文章で入力してください\n\n例:\n・来週の打ち合わせの日程調整をお願いしたい\n・候補日は火曜日または木曜日の午後\n・場所は御社でお願いしたい",
        help="詳細な文章でなくても、要点を箇条書きで入力すれば適切なメールが生成されます"
    )
    
    generate_button = st.button("🚀 メールを生成", type="primary", use_container_width=True)

with col2:
    st.subheader("📬 生成結果")
    result_container = st.container()

if generate_button:
    if not content.strip():
        st.warning("⚠️ メール内容を入力してください。")
    elif not relationship.strip() or not purpose.strip():
        st.warning("⚠️ 相手との関係とメールの目的を入力してください。")
    else:
        sender = {
            'company': sender_company,
            'department': sender_department,
            'position': sender_position,
            'last_name': sender_last_name,
            'first_name': sender_first_name,
            'email': sender_email,
            'phone': sender_phone,
            'mobile': sender_mobile
        }
        
        recipient = {
            'company': recipient_company,
            'department': recipient_department,
            'position': recipient_position,
            'last_name': recipient_last_name,
            'first_name': recipient_first_name
        }
        
        with st.spinner("メールを生成中..."):
            subject, body, issues = format_email(content, relationship, purpose, sender, recipient, is_internal)
        
        with result_container:
            if issues:
                st.warning("⚠️ 以下の点を確認してください:\n" + "\n".join(f"- {issue}" for issue in issues))
            else:
                st.success("✅ メールを生成しました！")
            
            # メールの種類を表示
            if is_internal:
                st.info("🏢 社内メール形式で生成されました")
            else:
                st.info("🌐 社外メール形式で生成されました")
            
            st.text_input("📌 件名", subject, disabled=True)
            st.text_area("📄 本文", body, height=450, disabled=True)
            
            # コピーボタン
            st.code(f"件名: {subject}\n\n{body}", language=None)
            st.info("💡 上記のボックス右上のコピーアイコンからコピーできます")

st.markdown("---")
st.caption("💡 ヒント: 社内/社外の区分と連絡先情報を入力すると、より実用的なメールが生成されます")

# フッター
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: gray; padding: 20px;'>
    <p>📧 ビジネスメール作成機 v1.0</p>
    <p style='font-size: 0.8em;'>Powered by Google Gemini AI | Built with Streamlit</p>
</div>
""", unsafe_allow_html=True)