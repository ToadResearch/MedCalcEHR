
[dataset](https://huggingface.co/datasets/ncbi/MedCalc-Bench-v1.0)

[fhir converter](https://github.com/ToadResearch/kiln-headless)

[model](https://huggingface.co/baichuan-inc/Baichuan-M2-32B)




If using API models, update API keys inside `.env.example`, and then run 

```sh
cp .env.example .env
```

Next, download the dataset and setup the FHIR-conversion tools. Here, `per-question` sets how many examples per 


```sh
chmod +x setup.sh
./setup.sh --per-question 1
```

Now we setup the LLM server (these are the default args, and are not necessary to include in the command)

```sh
chmod +x start_server.sh
./start_server.sh \
  --model-path baichuan-inc/Baichuan-M2-32B-GPTQ-Int4 \
  --served-model-name baichuan-m2-32b-gptq-int4 \
  --host 0.0.0.0 --port 30000 \
  --tp 4 --dp 2 \
  --dtype bfloat16 \
  --reasoning-parser qwen3 \
  --mem-fraction 0.9 \
  --cuda-graph-max-bs 2 \
  --attention-backend flashinfer
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