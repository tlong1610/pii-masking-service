import os

# Chỉ dùng regex và từ điển trong test: không tải mô hình, kết quả ổn định.
os.environ.setdefault("ENABLE_NER", "false")
