FROM python:3.13-slim

RUN apt-get update && \
    apt-get install -y openjdk-17-jre-headless wget unzip && \
    rm -rf /var/lib/apt/lists/*

RUN wget -O /usr/local/bin/bundletool.jar https://github.com/google/bundletool/releases/latest/download/bundletool-all-1.15.6.jar && \
    echo '#!/bin/bash\njava -jar /usr/local/bin/bundletool.jar "$@"' > /usr/local/bin/bundletool && \
    chmod +x /usr/local/bin/bundletool

RUN wget -O /tmp/smali.zip https://github.com/JesusFreke/smali/releases/download/v2.5.2/smali-2.5.2.zip && \
    apt-get update && apt-get install -y unzip && \
    unzip /tmp/smali.zip -d /opt/smali && \
    echo '#!/bin/bash\njava -jar /opt/smali/baksmali-2.5.2.jar "$@"' > /usr/local/bin/baksmali && \
    chmod +x /usr/local/bin/baksmali && \
    rm /tmp/smali.zip

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"] 