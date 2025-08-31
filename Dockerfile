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
&& apt-get clean \
&& rm -rf /var/lib/apt/lists/*

# Pythonライブラリをインストール
COPY requirements.txt /app/
RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

# mecab-ipadic-NEologdのインストール
RUN git clone --depth 1 https://github.com/neologd/mecab-ipadic-neologd.git
RUN echo yes | mecab-ipadic-neologd/bin/install-mecab-ipadic-neologd -n -a

# 辞書やフォントデータを更新
RUN sed -e "s!/var/lib/mecab/dic/debian!/usr/lib/x86_64-linux-gnu/mecab/dic/mecab-ipadic-neologd!g" /etc/mecabrc > /etc/mecabrc.new
RUN cp /etc/mecabrc /etc/mecabrc.org
RUN cp /etc/mecabrc.new /etc/mecabrc
RUN ln -s /etc/mecabrc /usr/local/etc/mecabrc
RUN apt-get update && apt-get -y install fonts-ipaexfont
RUN apt-get update && apt-get -y install fonts-noto-cjk
RUN rm /root/.cache/matplotlib -rf

# デジタルMATSUMOTOのPGをクローン
RUN git clone https://github.com/m07takash/DigitalMATSUMOTO.git /app/DigitalMATSUMOTO

# アプリケーションのソースコードをコピー
COPY . /app/

# ポートを解放
EXPOSE 8891
EXPOSE 8892
EXPOSE 8893
EXPOSE 8894
EXPOSE 8895
EXPOSE 8896
EXPOSE 8897
EXPOSE 8898
EXPOSE 8899
EXPOSE 8900

# ボリュームを設定
VOLUME /work

