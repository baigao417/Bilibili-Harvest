from runtime_config import DEFAULT_ARCHIVE_ROOT
from speech2text import load_whisper, run_analysis
from exAudio import process_audio_split
from utils import download_video


# 调试入口保留，仅供本地实验；正式使用请运行 window.py / launcher.py。
av = input("请输入 AV 号：")
filename = download_video(av[2:])
foldername = process_audio_split(filename)

load_whisper("small")
run_analysis(foldername, prompt="以下是普通话句子。")
output_path = f"{DEFAULT_ARCHIVE_ROOT}\\{foldername}.txt"
print("转换完成：", output_path)
