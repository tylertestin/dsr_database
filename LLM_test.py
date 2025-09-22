from transformers import AutoTokenizer, AutoModelForCausalLM

model_id = ""
tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(
    model_id, 
    device_map="auto", 
    local_files_only=True)

input_ids = tokenizer("Write a generic SQL query that could calculate an aveage from a database", return_tensors="pt").input_ids
output = model.generate(input_ids, max_new_tokens=100)
print(tokenizer.decode(output[0], skip_special_tokens=True))