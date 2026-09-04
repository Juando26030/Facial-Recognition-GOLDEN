FROM python:3.9-slim
RUN apt-get update && apt-get install -y cmake g++ make
WORKDIR /app
RUN pip install Flask face_recognition
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]