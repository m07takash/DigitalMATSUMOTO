import os
import re
import json
from datetime import datetime
from dotenv import load_dotenv
import DigiM_Util as dmu

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
user_folder_path = os.getenv("USER_FOLDER")
session_folder_prefix = os.getenv("SESSION_FOLDER_PREFIX")
session_file_name = os.getenv("SESSION_FILE_NAME")
temp_move_flg = os.getenv("TEMP_MOVE_FLG")

current_date = datetime.now()

# セッションの一覧を獲得
def get_session_list():
    session_nums = []
    for session_folder_name in os.listdir(user_folder_path):
        if session_folder_name.startswith(session_folder_prefix):
            match = re.match(rf'{session_folder_prefix}(\d+)', session_folder_name)
            if match:
                session_nums.append(int(match.group(1)))
    session_nums.sort()
    return session_nums    

# セッションIDを元にセッションの辞書データを取得する関数
def get_session_data(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = user_folder_path + session_key + "/" + session_file_name
    session_file_dict = dmu.read_json_file(session_file_path)    
    return session_file_dict

# 辞書データから最大のキーを取得する関数
def max_seq_dict(session_dict):
    max_seq = 0
    seqs = [int(k) for k in session_dict.keys() if k.isdigit()]
    if seqs:
        max_seq = max(seqs, key=int)
    return str(max_seq)

# セッション名を取得
def get_session_name(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = user_folder_path + session_key + "/" + session_file_name
    session_file_dict = dmu.read_json_file(session_file_path)   
    session_file_active_dict = {k: v for k, v in session_file_dict.items() if v.get("FLG") == "Y"}
    session_name = ""

    # 最大シーケンス／サブシーケンスからセッション名を取得
    if session_file_active_dict:
        max_seq = max_seq_dict(session_file_active_dict)
        max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
        session_name = session_file_active_dict[max_seq][max_sub_seq]["setting"]["session_name"]

    return session_name

# 新しいセッションIDを発番する
def set_new_session_id():
    new_session_num = max(get_session_list())+1 if get_session_list() else 0
    new_session_id = str(new_session_num)
    return new_session_id

# セッションクラス
class DigiMSession:
    def __init__(self, session_id="", session_name=""):
        self.session_id = session_id if session_id else set_new_session_id()
        self.session_name = session_name
        self.session_folder_path = user_folder_path + session_folder_prefix + self.session_id +"/" 
        self.session_file_path = self.session_folder_path +"/"+ session_file_name
        self.chat_history_dict = self.get_history()
        self.chat_history_active_dict = self.get_history_active()
        self.chat_history_active_omit_dict = self.get_history_active_omit()

    # 会話履歴を指定したseqとsub_seqまでで切り取り
    def extract_history_by_keys(self, chat_history_dict, seq_str="", sub_seq_str=""):
        trimmed_dict = {}
        if seq_str:
            for key, sub_dict in chat_history_dict.items():
                if key < seq_str:
                    trimmed_dict[key] = sub_dict
                elif key == seq_str:
                    if sub_seq_str:
                        trimmed_dict[key] = {sub_key: sub_dict[sub_key] for sub_key in sub_dict if sub_key <= sub_seq_str}
                    else:
                        trimmed_dict[key] = sub_dict
            return trimmed_dict
        else:
            return chat_history_dict

    # 全ての会話履歴を獲得する
    def get_history(self):
        chat_history_dict = {}
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(self.session_file_path)
        return chat_history_dict
    
    # 有効な会話履歴を獲得する
    def get_history_active(self):
        chat_history_active_dict = {}
        if self.chat_history_dict:
            chat_history_active_dict = {k: v for k, v in self.chat_history_dict.items() if v.get("FLG") == "Y"}
        return chat_history_active_dict

    # Sub_Seqの最大・最小の辞書型データを獲得する
    def get_history_active_omit(self):
        chat_history_active_omit_dict = {}
        if self.chat_history_active_dict:
            for key, sub_dict in self.chat_history_active_dict.items():
                sub_seqs = sorted((int(k) for k in sub_dict if k != "FLG"))
                # 最小サブキーと最大サブキーを取得
                min_subseq = str(sub_seqs[0])
                max_subseq = str(sub_seqs[-1])
                chat_history_active_omit_dict[key] = {}
                chat_history_active_omit_dict[key]["1"] = {}
                chat_history_active_omit_dict[key]["1"]["setting"] = sub_dict[str(min_subseq)]["setting"]
                chat_history_active_omit_dict[key]["1"]["prompt"] = sub_dict[str(min_subseq)]["prompt"]
                if "image" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["image"] = sub_dict[str(max_subseq)]["image"]
                chat_history_active_omit_dict[key]["1"]["response"] = sub_dict[str(max_subseq)]["response"]
                chat_history_active_omit_dict[key]["1"]["digest"] = sub_dict[str(max_subseq)]["digest"]
        return chat_history_active_omit_dict
    
    # 会話メモリを獲得する（トークン制限で切り取り）
    def get_memory(self, query_vec, model_name, tokenizer, memory_limit_tokens, memory_role="both", memory_priority="latest", memory_similarity_logic="cosine", memory_digest="Y", seq_limit="", sub_seq_limit=""):
        memories_list = []
        memories_list_prompt = []
        total_tokens = 0
        
        # アクティブな会話履歴からメモリに設定する履歴を取得
        chat_history_active_dict = self.extract_history_by_keys(self.chat_history_active_dict, seq_limit, sub_seq_limit)

        if chat_history_active_dict:
            max_seq = max(chat_history_active_dict.keys(), key=int)
            
            # 最新のダイジェストを取得
            if memory_digest == "Y":
                sub_seq_candidates = [k for k, v in chat_history_active_dict[max_seq].items() if isinstance(v, dict) and "digest" in v]
                if sub_seq_candidates:
                    max_sub_seq = max(sub_seq_candidates, key=int)
                    
                    # digestが含まれているか確認して処理を続ける
                    if "digest" in chat_history_active_dict[max_seq][max_sub_seq]:
                        # トークン制限を超えていなければ、ダイジェストを設定
                        total_tokens += chat_history_active_dict[max_seq][max_sub_seq]["digest"]["token"]
                        if total_tokens <= memory_limit_tokens:
                            similarity_prompt = dmu.calculate_similarity_vec(query_vec, chat_history_active_dict[max_seq][max_sub_seq]["digest"]["vec_text"], memory_similarity_logic)
                            memories_list.append({"seq": max_seq, "sub_seq": max_sub_seq, "type": "digest", "role": chat_history_active_dict[max_seq][max_sub_seq]["digest"]["role"], "timestamp": chat_history_active_dict[max_seq][max_sub_seq]["digest"]["timestamp"], "token": chat_history_active_dict[max_seq][max_sub_seq]["digest"]["token"], "similarity_prompt": similarity_prompt, "text": chat_history_active_dict[max_seq][max_sub_seq]["digest"]["text"], "vec_text": chat_history_active_dict[max_seq][max_sub_seq]["digest"]["vec_text"]})
        
            # 各履歴を取得
            for k, v in chat_history_active_dict.items():
                for k2, v2 in v.items():
                    if k2 != "FLG":
                        if memory_role in ["both", "user"]:
                            similarity_prompt = dmu.calculate_similarity_vec(query_vec, v2["prompt"]["query"]["vec_text"], memory_similarity_logic)
                            memories_list.append({"seq": k, "sub_seq": k2, "type": v2["prompt"]["role"], "role": v2["prompt"]["role"], "timestamp": v2["prompt"]["timestamp"], "token": v2["prompt"]["query"]["token"], "similarity_prompt": similarity_prompt, "text": v2["prompt"]["query"]["text"], "vec_text": v2["prompt"]["query"]["vec_text"]})
                        if memory_role in ["both", "assistant"]:
                            similarity_prompt = dmu.calculate_similarity_vec(query_vec, v2["response"]["vec_text"], memory_similarity_logic)
                            memories_list.append({"seq": k, "sub_seq": k2, "type": v2["response"]["role"], "role": v2["response"]["role"], "timestamp": v2["response"]["timestamp"], "token": v2["response"]["token"], "similarity_prompt": similarity_prompt, "text": v2["response"]["text"], "vec_text": v2["response"]["vec_text"]})

            # 各履歴をプライオリティ順に並び替え
            if memory_priority == "latest":
                memories_list_priority = sorted(memories_list, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"), reverse=True)
            elif memory_priority == "oldest":
                memories_list_priority = sorted(memories_list, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))
            elif memory_priority == "similar":
                memories_list_priority = sorted(memories_list, key=lambda x: x["similarity_prompt"])
            else :
                memories_list_priority = memories_list
            
            # トークン制限を超えないように会話メモリを設定
            memories_list_selected = []
            for memory_list_priority in memories_list_priority:
                total_tokens += memory_list_priority["token"]
                if total_tokens <= memory_limit_tokens:
                    memories_list_selected.append(memory_list_priority)

            # 最後にタイムスタンプでソート
            memories_list_prompt = sorted(memories_list_selected, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))
        
        return memories_list_prompt
    
    # 会話履歴を保存する
    def save_history(self, seq, chat_dict_key, chat_dict, sub_seq="1"):
        chat_history_dict = {}
        
        # セッションフォルダがなければ作成
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)

        # 保存済みの会話履歴を取得
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(self.session_file_path)

        # 会話履歴にseqがなければFLGと一緒に設定
        if seq not in chat_history_dict:
            chat_history_dict[seq] = {}
            chat_history_dict[seq]["FLG"] = "Y"

        # 会話履歴にsub_seqがなければ設定
        if sub_seq not in chat_history_dict[seq]:
            chat_history_dict[seq][sub_seq] = {}
        
        # 会話履歴を追加
        chat_history_dict[seq][sub_seq][chat_dict_key] = chat_dict

        # 会話履歴を保存
        with open(self.session_file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_history_dict, f, ensure_ascii=False, indent=4)

    # 会話履歴のシーケンスを発番する
    def get_seq_history(self):
        seq = 0
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            seq = max(int(key) for key in chat_history_dict.keys())
        return seq
    
    # 会話履歴のシーケンスを論理削除する
    def del_seq_history(self, seq):
        value = "N"
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq]["FLG"] = value
        with open(self.session_file_path, 'w', encoding='utf-8') as f:
            json.dump(chat_history_dict, f, ensure_ascii=False, indent=4)

    # 会話履歴の詳細情報を取得する
    def get_detail_info(self, seq, sub_seq="1"):
        chat_detail_info = ""
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict_seq = chat_history_dict[seq][sub_seq]
            
            chat_detail_info += "【設定情報】\n"
            for k, v in chat_history_dict_seq["setting"].items():
                chat_detail_info += f"{k}：{v}\n"

            chat_detail_info += "\n【実行情報】\n"
            chat_detail_info += "実行モデル："+chat_history_dict_seq["setting"]["model"]["FUNC_NAME"]+"("+str(chat_history_dict_seq["setting"]["model"]["PARAMETER"])+")\n"
            chat_detail_info += "プロンプトテンプレート："+chat_history_dict_seq["prompt"]["prompt_template"]["setting"]["PROMPT_FORMAT"]+"\n"
            chat_detail_info += "口調："+chat_history_dict_seq["prompt"]["prompt_template"]["setting"]["WRITING_STYLE"]+"\n"
            chat_detail_info += "RAGデータ："
            for rag_set_dict in chat_history_dict_seq["prompt"]["rag"]["setting"]:
                chat_detail_info += str(rag_set_dict["DATA"])
            chat_detail_info += "\n"

            chat_detail_info += "\n【実行結果】\n"
            chat_detail_info += "回答時間："+dmu.get_time_diff(chat_history_dict_seq["prompt"]["timestamp"], chat_history_dict_seq["response"]["timestamp"], format_str="%Y-%m-%d %H:%M:%S.%f")+"\n"
            chat_detail_info += "入力トークン数："+str(chat_history_dict_seq["prompt"]["token"])+"\n"
            chat_detail_info += "出力トークン数："+str(chat_history_dict_seq["response"]["token"])+"\n"

            chat_detail_info += "\n【会話のダイジェスト】(出力トークン数："+str(chat_history_dict_seq["digest"]["token"])+")\n"
            chat_detail_info += str(chat_history_dict_seq["digest"]["text"])+"\n"

            chat_detail_info += "\n【メモリ】\n"
            for memory_set_dict in chat_history_dict_seq["response"]["reference"]["memory"]:
                chat_detail_info += memory_set_dict["log"]
        
            chat_detail_info += "\n【RAGコンテキスト】\n"
            for rag_set_dict in chat_history_dict_seq["response"]["reference"]["rag"]:
                chat_detail_info += rag_set_dict["log"]

            chat_detail_info += "\n【コンテンツコンテキスト】"
            for content_dict in chat_history_dict_seq["prompt"]["query"]["contents"]:
                chat_detail_info += content_dict["context"]
                
        return chat_detail_info

    # コンテンツファイルを保存する
    def save_contents_file(self, from_file_path, content_file_name):
        to_folder_path = self.session_folder_path +"contents/"
        to_file_path = to_folder_path + content_file_name
        # コンテンツフォルダがなければ作成
        if not os.path.exists(to_folder_path):
            os.makedirs(to_folder_path, exist_ok=True)
        if temp_move_flg == "Y":
            dmu.copy_file(from_file_path, to_file_path)