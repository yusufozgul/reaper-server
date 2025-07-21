FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y openjdk-17-jre-headless wget unzip && \
    rm -rf /var/lib/apt/lists/*

RUN wget -O /usr/local/bin/bundletool.jar https://github.com/google/bundletool/releases/download/1.18.1/bundletool-all-1.18.1.jar && \
    echo '#!/bin/bash\njava -jar /usr/local/bin/bundletool.jar "$@"' > /usr/local/bin/bundletool && \
    chmod +x /usr/local/bin/bundletool

RUN wget -O /tmp/smali.zip https://bitbucket.org/JesusFreke/smali/get/cbd41d36ccde.zip && \
    unzip /tmp/smali.zip -d /tmp/ && \
    find /tmp -name "baksmali*.jar" -exec cp {} /usr/local/bin/baksmali.jar \; && \
    echo '#!/bin/bash\njava -jar /usr/local/bin/baksmali.jar "$@"' > /usr/local/bin/baksmali && \
    chmod +x /usr/local/bin/baksmali && \
    rm -rf /tmp/smali.zip /tmp/JesusFreke-smali-*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"] 