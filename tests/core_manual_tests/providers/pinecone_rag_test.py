import agentops
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
import numpy as np
import os
import time
from openai import OpenAI
import tiktoken

load_dotenv()

# Initialize clients
openai_client = OpenAI()
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

# Test dataset - State of the Union paragraphs
SAMPLE_TEXTS = [
    "The state of our Union is strong because our people are strong. Over the last year, we've made progress. Created jobs. Reduced deficit. Lowered prescription drug costs.",
    "We are the only country that has emerged from every crisis stronger than when we entered it. That is what we are doing again.",
    "We have more to do, but here is the good news: Our country is stronger today than we were a year ago.",
    "As I stand here tonight, we have created a record 12 million new jobs – more jobs created in two years than any president has ever created in four years.",
    "For decades, the middle class was hollowed out. Too many good-paying manufacturing jobs moved overseas. Factories closed down.",
]

def get_embedding(text, model="text-embedding-3-small"):
    """Get OpenAI embedding for text"""
    response = openai_client.embeddings.create(
        model=model,
        input=text,
        encoding_format="float"
    )
    return response.data[0].embedding

def create_index(index_name, dimension):
    """Create Pinecone index"""
    print(f"\nCreating index {index_name}...")
    
    try:
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric="cosine",
            spec=ServerlessSpec(
                cloud="aws",
                region="us-east-1"
            )
        )
        
        # Wait for index to be ready
        while True:
            try:
                status = pc.describe_index(index_name).status['ready']
                if status:
                    break
                time.sleep(1)
            except Exception as e:
                print(f"Waiting for index to be ready... ({str(e)})")
                time.sleep(1)
                continue
                
        return pc.Index(index_name)
        
    except Exception as e:
        print(f"Error creating index: {e}")
        raise

def index_documents(index, texts):
    """Index documents with their embeddings"""
    print("\nIndexing documents...")
    vectors = []
    
    for i, text in enumerate(texts):
        embedding = get_embedding(text)
        vectors.append((f"doc{i}", embedding, {"text": text}))
    
    upsert_response = index.upsert(
        vectors=vectors,
        namespace="test-namespace"
    )
    print(f"Indexed {len(vectors)} documents")
    return upsert_response

def query_similar(index, query, top_k=2):
    """Query similar documents"""
    print(f"\nQuerying: {query}")
    query_embedding = get_embedding(query)
    
    results = index.query(
        vector=query_embedding,
        top_k=top_k,
        namespace="test-namespace",
        include_metadata=True
    )
    
    # Add debug information
    print(f"Found {len(results.matches)} matches")
    for match in results.matches:
        print(f"Score: {match.score:.4f}, Text: {match.metadata['text'][:100]}...")
    
    return results

def generate_answer(query, context):
    """Generate answer using OpenAI"""
    prompt = f"""Based on the following context, answer the question. 
    If the answer cannot be found in the context, say "I cannot answer this based on the provided context."

    Context:
    {context}

    Question: {query}
    """
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",  
        messages=[
            {"role": "system", "content": "You are a helpful assistant that answers questions based on provided context."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

def test_data_plane_operations(index):
    """Test various data plane operations"""
    print("\nTesting data plane operations...")
    
    try:
        # Test list
        print("\nTesting list vector IDs...")
        vector_ids = list(index.list(namespace="test-namespace"))
        print(f"List response: {vector_ids}")
        
        # Test describe index stats
        print("\nTesting describe index stats...")
        stats = index.describe_index_stats()
        print(f"Index stats: {stats}")
        
        # Test fetch
        print("\nTesting fetch vectors...")
        if vector_ids:  # Only fetch if we have vector IDs
            fetch_response = index.fetch(
                ids=vector_ids[:2],  # Get first 2 IDs
                namespace="test-namespace"
            )
            print(f"Fetch response: {fetch_response}")
        
        # Test update
        print("\nTesting update vector...")
        try:
            if vector_ids:  # Only update if we have vector IDs
                # Create a random vector of the correct dimension
                random_vector = np.random.rand(1536).tolist()
                update_response = index.update(
                    id=vector_ids[0],
                    values=random_vector,
                    namespace="test-namespace"
                )
                print(f"Update response: {update_response}")
        except Exception as e:
            print(f"Update operation error: {e}")
            
    except Exception as e:
        print(f"Error in data plane operations: {e}")

def test_additional_operations(pc):
    """Test semantic search operations"""
    print("\nTesting semantic search operations...")
    try:
        # Test embedding using OpenAI
        print("\nTesting OpenAI embedding...")
        try:
            response = openai_client.embeddings.create(
                model="text-embedding-3-small",
                input="test document",
                encoding_format="float"
            )
            embedding = response.data[0].embedding
            print(f"Generated embedding of dimension {len(embedding)}")
            
            # Use the embedding for semantic search
            print("\nTesting semantic search with embedding...")
            index = pc.Index("test-index-rag")
            results = index.query(
                vector=embedding,
                top_k=2,
                namespace="test-namespace",
                include_metadata=True
            )
            
            print("\nSearch results:")
            for match in results.matches:
                print(f"ID: {match.id}, Score: {match.score}")
                if hasattr(match, 'metadata'):
                    print(f"Metadata: {match.metadata}")
                print("---")
                
        except Exception as e:
            print(f"Search operation error: {str(e)}")
            
    except Exception as e:
        print(f"Error in semantic search operations: {str(e)}")

def test_rag_pipeline():
    """Test complete RAG pipeline with additional operations"""
    index_name = "test-index-rag"
    dimension = 1536  # Dimension for text-embedding-3-small
    
    try:
        # List existing indexes
        print("\nListing indexes...")
        indexes = pc.list_indexes()
        print(f"Current indexes: {indexes}")
        
        # Create new index if needed
        if index_name not in indexes:
            index = create_index(index_name, dimension)
        else:
            # Delete existing index to start fresh
            pc.delete_index(index_name)
            time.sleep(2)  # Wait for deletion
            index = create_index(index_name, dimension)
        
        # Index sample documents
        print("\nWaiting for index to be ready...")
        time.sleep(5)  # Add delay to ensure index is ready
        
        index_documents(index, SAMPLE_TEXTS)
        print("Waiting for documents to be indexed...")
        time.sleep(5)  # Add delay to ensure documents are indexed
        
        # Test data plane operations
        test_data_plane_operations(index)
        
        # Test additional operations
        test_additional_operations(pc)
        
        # Test queries
        test_queries = [
            "How many new jobs were created according to the speech?",
            "What happened to manufacturing jobs and the middle class?",
            "What is the current state of the Union?",
            "What about education?" # This should get "cannot answer" response
        ]
        
        for query in test_queries:
            # Get similar documents
            results = query_similar(index, query)
            
            # Extract context from results
            context = "\n".join([match.metadata["text"] for match in results.matches])
            
            # Generate answer
            answer = generate_answer(query, context)
            print(f"\nQ: {query}")
            print(f"A: {answer}")
            print(f"Context used: {context}\n")
            print("-" * 50)
            time.sleep(1)  # Rate limiting
        
        # Clean up
        print("\nCleaning up...")
        pc.delete_index(index_name)
        print(f"Index {index_name} deleted")
        
    except Exception as e:
        print(f"Error during testing: {e}")
        agentops.end_session(end_state="Fail")
        return
    
    agentops.end_session(end_state="Success")
    print("\nTest completed successfully!")

if __name__ == "__main__":
    agentops.init(default_tags=["pinecone-rag-test"])
    test_rag_pipeline()