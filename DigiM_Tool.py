import os
from dotenv import load_dotenv
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Context as dmc

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
charactor_folder_path = os.getenv("CHARACTOR_FOLDER")
mst_folder_path = os.getenv("MST_FOLDER")
openai_api_key = os.getenv("OPENAI_API_KEY")

# 会話のダイジェスト生成
def dialog_digest(agent_data, query, memories_selected={}):
    tool_agent_mode = "DIALOG_DIGEST"
    tool_agent = dma.DigiM_Agent(agent_data, tool_agent_mode)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_template = tool_agent.set_prompt_template()

    # プロンプトの設定
    prompt = f'{prompt_template}{query}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = tool_agent.generate_response(prompt, memories_selected)

    # 出力形式
    response = "【これまでの会話のダイジェスト】\n" + response
    
    return response, prompt_tokens, response_tokens


# 画像データへの批評の生成
def art_critics(agent_data, memories_selected={}, image_paths=[]):
    tool_agent_mode = "ART_CRITIC"
    tool_agent = dma.DigiM_Agent(agent_data, tool_agent_mode)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_template = tool_agent.set_prompt_template()

    # プロンプトの設定
    prompt = f'{prompt_template}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = tool_agent.generate_response(prompt, memories_selected, image_paths)
    
    return response, prompt_tokens, response_tokens


# エシカルチェック
def ethical_check(agent_data, query, memories_selected={}):
    tool_agent_mode = "ETHICAL_CHECK"
    tool_agent = dma.DigiM_Agent(agent_data, tool_agent_mode)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_template = tool_agent.set_prompt_template()

    # プロンプトの設定
    # prompt = f'{rag_context}{prompt_template}{query}{text_contents}'
    prompt = f'{prompt_template}{query}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = tool_agent.generate_response(prompt, memories_selected)
    
    return response, prompt_tokens, response_tokens


# 川柳の作成
def senryu_sensei(agent_data, query, memories_selected={},):
    tool_agent_mode = "SENRYU_SENSEI"
    tool_agent = dma.DigiM_Agent(agent_data, tool_agent_mode)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_template = tool_agent.set_prompt_template()

    # プロンプトの設定
    prompt = f'{rag_context}{prompt_template}{query}'
    
    # LLMの実行
    response, completion, prompt_tokens, response_tokens = tool_agent.generate_response(prompt, memories_selected)
    
    return response, prompt_tokens, response_tokens

