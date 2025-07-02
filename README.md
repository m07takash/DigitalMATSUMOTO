### セットアップ
前提：ubuntu22.04以上の安定板
1. GithubのdockerフォルダにあるDockerfile/requirements.txtをダウンロードして格納 
2. Dockerイメージをビルド  
　docker build -t <Dockerイメージ名> .
3. Dockerコンテナを作成  
　docker run -d --restart unless-stopped --name <Dockerコンテナ名> -it -v ~/demo:/work -p 8891-8900:8891-8900 <Dockerイメージ名>
4. Dockerコンテナに入って、Gitクローン  
　git clone https://github.com/m07takash/DigitalMATSUMOTO.git
5. APIキーの設定  
　system.env_sampleをsystem.envに名前を変更して、ファイルを開き、OpenAIのAPIキーを設定
