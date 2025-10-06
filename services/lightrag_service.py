"""
LightRAG service for the Telegram bot.
"""

import logging
import httpx
import re
from typing import Optional, Dict, Any, Set

from config import Config

logger = logging.getLogger(__name__)

class LightRAGService:
    """Service for interacting with LightRAG API."""
    
    def __init__(self):
        """Initialize the LightRAG service."""
        self.base_url = Config.LIGHTRAG_BASE_URL
        self.api_key = Config.LIGHTRAG_API_KEY
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
    
    async def query(self, query_text: str, mode: str = "global") -> Optional[str]:
        """
        Query the LightRAG system.
        
        Args:
            query_text: The query text
            mode: Query mode (mix, naive, local, global)
            
        Returns:
            Response text if successful, None otherwise
        """
        endpoint = f"{self.base_url}/query"
        
        payload = {
            "query": query_text,
            "mode": mode,
            "response_type": "string",
            "top_k": 60,
            "chunk_top_k": 30,
            "max_entity_tokens": 4000,
            "max_relation_tokens": 4000,
            "max_total_tokens": 32000,
            "enable_rerank": True
        }
        
        logger.info("🌐 LightRAG HTTP Request Details:")
        logger.info(f"   📍 URL: {endpoint}")
        logger.info(f"   📦 Payload: {payload}")
        logger.info(f"   🔑 Headers: {self.headers}")
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                logger.info("⏳ Sending request to LightRAG...")
                response = await client.post(endpoint, json=payload, headers=self.headers)
                
                logger.info(f"📨 LightRAG HTTP Response:")
                logger.info(f"   ✅ Status: {response.status_code}")
                logger.info(f"   📊 Response size: {len(response.text)} chars")
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"   📋 Response type: {type(result)}")
                    
                    if isinstance(result, dict) and "response" in result:
                        rag_response = result["response"]
                        logger.info(f"🎯 LightRAG Full Response Analysis:")
                        logger.info(f"   📊 Response length: {len(rag_response)} chars")
                        logger.info(f"   📄 Full response preview (first 1000 chars):")
                        logger.info(f"   {rag_response[:1000]}{'...' if len(rag_response) > 1000 else ''}")
                        if len(rag_response) > 1000:
                            logger.info(f"   📄 Response end (last 500 chars):")
                            logger.info(f"   ...{rag_response[-500:]}")
                        
                        return rag_response
                    else:
                        logger.warning(f"❌ Unexpected response format: {result}")
                        logger.info(f"   📄 Raw result: {str(result)[:500]}...")
                        return str(result)
                else:
                    logger.error(f"❌ LightRAG query failed:")
                    logger.error(f"   🔴 Status: {response.status_code}")
                    logger.error(f"   📄 Response: {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error("LightRAG query timed out")
            return None
        except Exception as e:
            logger.error(f"Error querying LightRAG: {e}")
            return None
    
    async def stream_query(self, query_text: str, mode: str = "global"):
        """
        Stream query the LightRAG system.
        
        Args:
            query_text: The query text
            mode: Query mode (mix, naive, local, global)
            
        Yields:
            Response chunks as they arrive
        """
        endpoint = f"{self.base_url}/query/stream"
        
        payload = {
            "query": query_text,
            "mode": mode,
            "response_type": "string",
            "top_k": 60,
            "chunk_top_k": 30,
            "max_entity_tokens": 4000,
            "max_relation_tokens": 4000,
            "max_total_tokens": 32000,
            "enable_rerank": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", endpoint, json=payload, headers=self.headers) as response:
                    if response.status_code == 200:
                        async for chunk in response.aiter_text():
                            if chunk.strip():
                                yield chunk
                    else:
                        logger.error(f"LightRAG stream query failed with status {response.status_code}")
                        
        except Exception as e:
            logger.error(f"Error streaming LightRAG query: {e}")
    
    async def check_health(self) -> bool:
        """
        Check if LightRAG service is available.

        Returns:
            True if service is available, False otherwise
        """
        endpoint = f"{self.base_url}/health"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(endpoint, headers=self.headers)
                return response.status_code == 200

        except Exception as e:
            logger.error(f"Error checking LightRAG health: {e}")
            return False

    async def check_relevance(self, message: str) -> Dict[str, Any]:
        """
        Check if the knowledge base contains relevant information for the given message.

        Args:
            message: The user's message to check for relevance

        Returns:
            Dictionary with relevance analysis:
            {
                'is_relevant': bool,
                'reason': str,
                'context_length': int
            }
        """
        logger.info("🔍 LightRAG Relevance Check:")
        logger.info(f"   📝 Message: {message[:200]}{'...' if len(message) > 200 else ''}")

        try:
            # Query LightRAG with specific parameters for relevance checking
            endpoint = f"{self.base_url}/query"

            payload = {
                "query": message,
                "mode": "naive",
                "response_type": "string",
                "top_k": 5,
                "chunk_top_k": 5,
                "max_entity_tokens": 1000,
                "max_relation_tokens": 1000,
                "max_total_tokens": 8000,
                "enable_rerank": True
            }

            logger.debug(f"   📦 Relevance query payload: {payload}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(endpoint, json=payload, headers=self.headers)

                if response.status_code != 200:
                    logger.error(f"❌ LightRAG relevance query failed: {response.status_code}")
                    return {
                        'is_relevant': False,
                        'reason': f'API error: {response.status_code}',
                        'context_length': 0
                    }

                result = response.json()
                context = ""

                if isinstance(result, dict) and "response" in result:
                    context = result["response"]
                else:
                    context = str(result)

                context_length = len(context)
                logger.info(f"   📊 Retrieved context length: {context_length} chars")

                # Check 1: Minimum content length (200 characters)
                if context_length < 200:
                    logger.info(f"   ❌ Context too short: {context_length} < 200 chars")
                    return {
                        'is_relevant': False,
                        'reason': f'Insufficient context retrieved ({context_length} chars < 200 required)',
                        'context_length': context_length
                    }

                # Check 2: Word intersection analysis (minimum 20%)
                intersection_percentage = self._calculate_word_intersection(message, context)
                logger.info(f"   📊 Word intersection: {intersection_percentage:.1f}%")

                if intersection_percentage < 20.0:
                    logger.info(f"   ❌ Low word intersection: {intersection_percentage:.1f}% < 20%")
                    return {
                        'is_relevant': False,
                        'reason': f'Low content relevance ({intersection_percentage:.1f}% word intersection < 20% required)',
                        'context_length': context_length
                    }

                # All checks passed
                logger.info(f"   ✅ Content is relevant: {context_length} chars, {intersection_percentage:.1f}% intersection")
                return {
                    'is_relevant': True,
                    'reason': f'Relevant content found ({context_length} chars, {intersection_percentage:.1f}% word intersection)',
                    'context_length': context_length
                }

        except httpx.TimeoutException:
            logger.error("❌ LightRAG relevance check timed out")
            return {
                'is_relevant': False,
                'reason': 'Timeout during relevance check',
                'context_length': 0
            }
        except Exception as e:
            logger.error(f"❌ Error checking LightRAG relevance: {e}")
            return {
                'is_relevant': False,
                'reason': f'Error during relevance check: {str(e)}',
                'context_length': 0
            }

    def _calculate_word_intersection(self, message: str, context: str) -> float:
        """
        Calculate the percentage of words from the message that appear in the context.

        Args:
            message: The user's message
            context: The retrieved context from LightRAG

        Returns:
            Percentage of message words found in context (0-100)
        """
        try:
            # Normalize and extract words from message
            message_words = self._extract_words(message.lower())
            context_words = self._extract_words(context.lower())

            if not message_words:
                logger.warning("⚠️ No words found in message for intersection analysis")
                return 0.0

            # Calculate intersection
            intersection = message_words.intersection(context_words)
            intersection_percentage = (len(intersection) / len(message_words)) * 100

            logger.debug(f"   📊 Word analysis:")
            logger.debug(f"      Message words: {len(message_words)}")
            logger.debug(f"      Context words: {len(context_words)}")
            logger.debug(f"      Intersection: {len(intersection)}")
            logger.debug(f"      Intersection words: {list(intersection)[:10]}...")

            return intersection_percentage

        except Exception as e:
            logger.error(f"❌ Error calculating word intersection: {e}")
            return 0.0

    def _extract_words(self, text: str) -> Set[str]:
        """
        Extract meaningful words from text (excluding short words and common stop words).

        Args:
            text: Text to extract words from

        Returns:
            Set of meaningful words
        """
        # Basic Russian stop words to exclude
        stop_words = {
            'и', 'в', 'не', 'на', 'я', 'быть', 'с', 'что', 'а', 'по', 'это', 'она', 'так', 'его', 'но', 'да', 'ты', 'к', 'у', 'же', 'вы', 'за', 'бы', 'во', 'только', 'о', 'уже', 'для', 'вот', 'кто', 'когда', 'если', 'или', 'из', 'до', 'от', 'как', 'то', 'где', 'такой', 'тот', 'мы', 'эти', 'можно', 'есть', 'что-то', 'при', 'нет', 'они', 'все', 'под', 'без', 'раз', 'над', 'об', 'со', 'год', 'день', 'два', 'три', 'чем', 'между', 'перед', 'около', 'среди', 'через', 'после'
        }

        # Extract words using regex (letters and numbers, minimum 3 characters)
        words = set(re.findall(r'\b[а-яё\w]{3,}\b', text, re.IGNORECASE))

        # Remove stop words
        meaningful_words = words - stop_words

        return meaningful_words