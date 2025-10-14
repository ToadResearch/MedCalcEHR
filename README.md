it should append both the clinical note and fhir bundle to the rows

have it print these two file paths at the end 

have the run.sh file accept args about the number of examples per question type...
then have this pass into the download_data.py file 

flow:

5) create task files from them and automatically push, or have them download from HF and create tasks...
6) upload this dataset

https://huggingface.co/datasets/ncbi/MedCalc-Bench-v1.0

https://github.com/jmandel/kiln

https://huggingface.co/baichuan-inc/Baichuan-M2-32B




If using API models, update API keys inside `.env.example`, and then run 

```sh
cp .env.example .env
```

Next, download the dataset and setup the FHIR-conversion tools. Here, `per-question` sets how many examples per 


```sh
chmod +x setup.sh
./setup.sh --per-question 1
```

Now we setup the LLM server

```sh
chmod +x start_server.sh
./start_server.sh \
  --model-path baichuan-inc/Baichuan-M2-32B-GPTQ-Int4 \
  --port 30000 \
  --tp 4 \
  -- dp 2 \
  --dtype bfloat16 \
  --reasoning-parser qwen3 \
  --mem-fraction 0.9 \
  --cuda-graph-max-bs 2 \
  --kv-cache-dtype fp8_e4m3 \
  --attention-backend flashinfer \
  --speculative-algorithm EAGLE3 \
  --speculative-draft-model-path baichuan-inc/Baichuan-M2-32B-GPTQ-Int4/draft \
  --speculative-num-steps 6 \
  --speculative-eagle-topk 10 \
  --speculative-num-draft-tokens 32
```

Next we can run the process

```sh
chmod +x run.sh
./run.sh
```

And finally upload the data to HuggingFace

```sh
huggingface-cli login 
```

```sh
python upload_to_hf.py \
    --hf_username mkieffer \
    --hf_repo_name MedCalcEHR \
    --private false
```