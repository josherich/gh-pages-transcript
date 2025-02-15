import ollama
import chromadb
import uuid

client = chromadb.Client()
col = client.create_collection(name="docs")

def add_vector_index(sentence):
    response = ollama.embed(model='mxbai-embed-large', input=sentence)
    embeddings = response['embeddings']
    print(f"Embedding: {embeddings[0][0:10]} ...", len(embeddings[0]))
    col.add(
        ids=[str(uuid.uuid4().hex)],
        metadatas=[{"article": "1", "sent": 1}],
        embeddings=embeddings,
        documents=[sentence]
    )
    return embeddings

def search(query):
    response = ollama.embed(model='mxbai-embed-large', input=query)
    print(f"Query embedding: {response['embeddings'][0][0:10]} ...", len(response['embeddings'][0]))
    res = col.query(query_embeddings=response['embeddings'], n_results=5)
    return res

if __name__ == "__main__":
    sentence1 = "The quick brown fox jumps over the lazy dog"
    sentence2 = "Llamas are members of the camelid family meaning they're pretty closely related to vicuñas and camels"
    add_vector_index(sentence1)
    add_vector_index(sentence2)

    query = "llamas"
    print(search(query))
