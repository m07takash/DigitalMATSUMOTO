#!/bin/bash
# DigitalMATSUMOTO Startup Script
# コンテナ起動時に各サービスをバックグラウンドで起動する

cd /app/DigitalMATSUMOTO

# Streamlit (modified) をポート8895で起動
nohup streamlit run WebDigiMatsuAgent_modified.py --server.address 0.0.0.0 --server.port 8895 > /dev/null 2>&1 &

# FastAPI を8899ポートで起動
nohup gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8899 DigiM_API:app --timeout 600 --graceful-timeout 600 --keep-alive 5 --capture-output --log-level debug >> /var/log/digim_api.log 2>&1 &

# メインのStreamlitをフォアグラウンドで起動（コンテナのメインプロセス）
exec streamlit run WebDigiMatsuAgent.py --server.port 8501 --server.address 0.0.0.0
