import os
import sys

print("Starting model download script...")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

try:
    from fastembed import TextEmbedding
    print("FastEmbed imported successfully. Downloading model BAAI/bge-small-zh-v1.5...")
    # Cache the model in the local directory 'fastembed_cache'
    model = TextEmbedding(model_name='BAAI/bge-small-zh-v1.5', cache_dir='./fastembed_cache')
    print("Download completed successfully!")
except Exception as e:
    print(f"Error occurred: {e}", file=sys.stderr)
    sys.exit(1)
