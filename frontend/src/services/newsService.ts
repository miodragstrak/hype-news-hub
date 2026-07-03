import type { CollectArticlesResponse, DiscoveryResult, EditorialQueueResponse, StoriesResponse } from "../types/news";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function getDiscoverySources(): Promise<DiscoveryResult[]> {
  const response = await fetch(`${API_BASE_URL}/api/discovery`);

  if (!response.ok) {
    throw new Error("Unable to fetch source discovery");
  }

  return response.json() as Promise<DiscoveryResult[]>;
}

export async function collectLatestNews(): Promise<CollectArticlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/collect`);

  if (!response.ok) {
    throw new Error("Collection failed. Please try again.");
  }

  return response.json() as Promise<CollectArticlesResponse>;
}

export async function getStories(): Promise<StoriesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/stories`);

  if (!response.ok) {
    throw new Error("Unable to fetch stories");
  }

  return response.json() as Promise<StoriesResponse>;
}

export async function getEditorialQueue(): Promise<EditorialQueueResponse> {
  const response = await fetch(`${API_BASE_URL}/api/editorial-queue`);

  if (!response.ok) {
    throw new Error("Unable to fetch editorial queue");
  }

  return response.json() as Promise<EditorialQueueResponse>;
}
