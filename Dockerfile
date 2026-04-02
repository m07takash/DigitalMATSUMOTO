# Ubuntuをベースとする
FROM ubuntu:22.04

# 環境変数の設定
ENV DEBIAN_FRONTEND=noninteractive

# 作業ディレクトリを設定
WORKDIR /app

# /work ディレクトリの作成と権限設定
RUN mkdir -p /work && \
chmod 777 /work

# 必要なパッケージをインストール
RUN apt-get update && apt-get install -y sudo \
make \
curl \
xz-utils \
file \
git \
python3 \
python3-pip \
gcc \
g++ \
mecab \
libmecab-dev \
mecab-ipadic-utf8 \
fonts-ipaexfont \
fonts-noto-cjk \
&& apt-get clean \
&& rm -rf /var/lib/apt/lists/*

# Pythonライブラリをインストール
COPY requirements.txt /app/
RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

# mecab-ipadic-NEologdのインストール
RUN git clone --depth 1 https://github.com/neologd/mecab-ipadic-neologd.git \
&& echo yes | mecab-ipadic-neologd/bin/install-mecab-ipadic-neologd -n -a \
&& rm -rf mecab-ipadic-neologd

# 辞書やフォントデータを更新
RUN sed -e "s!/var/lib/mecab/dic/debian!/usr/lib/x86_64-linux-gnu/mecab/dic/mecab-ipadic-neologd!g" /etc/mecabrc > /etc/mecabrc.new \
&& cp /etc/mecabrc /etc/mecabrc.org \
&& cp /etc/mecabrc.new /etc/mecabrc \
&& ln -s /etc/mecabrc /usr/local/etc/mecabrc \
&& rm /root/.cache/matplotlib -rf

# アプリケーションのソースコードをコピー
COPY . /app/DigitalMATSUMOTO/

# 作業ディレクトリをアプリケーションに設定
WORKDIR /app/DigitalMATSUMOTO

# ポートを解放
EXPOSE 8501
EXPOSE 8891
EXPOSE 8899

# ボリュームを設定
VOLUME /work

# ポート8895を追加
EXPOSE 8895

# デフォルトの起動コマンド（startup.shで複数サービスを起動）
CMD ["/bin/bash", "startup.sh"]
