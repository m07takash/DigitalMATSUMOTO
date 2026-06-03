# Base image: Ubuntu
FROM ubuntu:22.04

# Environment variables
ENV DEBIAN_FRONTEND=noninteractive

# Working directory
WORKDIR /app

# Create /work and set permissions
RUN mkdir -p /work && \
chmod 777 /work

# Install required packages
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

# Install Python libraries
COPY requirements.txt /app/
RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

# Install mecab-ipadic-NEologd
RUN git clone --depth 1 https://github.com/neologd/mecab-ipadic-neologd.git \
&& echo yes | mecab-ipadic-neologd/bin/install-mecab-ipadic-neologd -n -a \
&& rm -rf mecab-ipadic-neologd

# Update dictionary and font data
RUN sed -e "s!/var/lib/mecab/dic/debian!/usr/lib/x86_64-linux-gnu/mecab/dic/mecab-ipadic-neologd!g" /etc/mecabrc > /etc/mecabrc.new \
&& cp /etc/mecabrc /etc/mecabrc.org \
&& cp /etc/mecabrc.new /etc/mecabrc \
&& ln -s /etc/mecabrc /usr/local/etc/mecabrc \
&& rm /root/.cache/matplotlib -rf

# Copy the application source code
COPY . /app/DigitalMATSUMOTO/

# Switch the working directory to the application
WORKDIR /app/DigitalMATSUMOTO

# Expose ports
EXPOSE 8501
EXPOSE 8891
EXPOSE 8899

# Volume mount point
VOLUME /work

# Additional port 8895
EXPOSE 8895

# Default startup command (startup.sh launches multiple services)
CMD ["/bin/bash", "startup.sh"]
