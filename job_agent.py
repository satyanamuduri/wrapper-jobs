#!/usr/bin/env python3
"""Job search agent - scrapes Indeed and LinkedIn, scores against your profile."""

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
import json
import argparse
import time
import random
import re


@dataclass
class Job:
    title: str
    company: str
    location: str
    summary: str
    url: str
    source: str = ""
    salary: str = ""
    match_score: float = 0.0
    matched_skills: list = field(default_factory=list)
    missing_skills: list = field(default_factory=list)


class IndeedScraper:
    BASE_URL = "https://www.indeed.com/jobs"

    def scrape(self, keywords, location, pages, headers) -> list[Job]:
        jobs = []
        for page in range(pages):
            params = {"q": keywords, "l": location, "start": page * 10}
            try:
                resp = requests.get(self.BASE_URL, params=params,
                                    headers=headers, timeout=10)
                resp.raise_for_status()
                jobs.extend(self._parse(resp.text))
                time.sleep(random.uniform(1, 3))
            except requests.RequestException as e:
                print(f"  Indeed page {page} error: {e}")
        return jobs

    def _parse(self, html: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for card in soup.select("div.job_seen_beacon"):
            title_el = card.select_one("h2.jobTitle a, h2.jobTitle span")
            company_el = card.select_one("[data-testid='company-name']")
            location_el = card.select_one("[data-testid='text-location']")
            summary_el = card.select_one("div.job-snippet, td.resultContent div")
            salary_el = card.select_one("[data-testid='attribute_snippet_testid']")
            link_el = card.select_one("h2.jobTitle a")
            if not title_el:
                continue
            url = ""
            if link_el and link_el.get("href"):
                href = link_el["href"]
                url = f"https://www.indeed.com{href}" if href.startswith("/") else href
            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "N/A",
                location=location_el.get_text(strip=True) if location_el else "N/A",
                summary=summary_el.get_text(strip=True) if summary_el else "",
                salary=salary_el.get_text(strip=True) if salary_el else "",
                url=url,
                source="Indeed",
            ))
        return jobs


class LinkedInScraper:
    BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def scrape(self, keywords, location, pages, headers) -> list[Job]:
        jobs = []
        for page in range(pages):
            params = {
                "keywords": keywords,
                "location": location,
                "start": page * 25,
            }
            try:
                resp = requests.get(self.BASE_URL, params=params,
                                    headers=headers, timeout=10)
                resp.raise_for_status()
                jobs.extend(self._parse(resp.text))
                time.sleep(random.uniform(2, 4))
            except requests.RequestException as e:
                print(f"  LinkedIn page {page} error: {e}")
        return jobs

    def _parse(self, html: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for card in soup.select("li"):
            title_el = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle a")
            location_el = card.select_one("span.job-search-card__location")
            link_el = card.select_one("a.base-card__full-link")
            if not title_el:
                continue
            jobs.append(Job(
                title=title_el.get_text(strip=True),
                company=company_el.get_text(strip=True) if company_el else "N/A",
                location=location_el.get_text(strip=True) if location_el else "N/A",
                summary="",
                url=link_el["href"].split("?")[0] if link_el else "",
                source="LinkedIn",
            ))
        return jobs


class JobSearchAgent:
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    def __init__(self, keywords: str, location: str = "", profile: dict = None,
                 sources: list = None):
        self.keywords = keywords
        self.location = location
        self.profile = profile or {}
        self.sources = sources or ["indeed", "linkedin"]
        self.scrapers = {
            "indeed": IndeedScraper(),
            "linkedin": LinkedInScraper(),
        }

    def search(self, pages: int = 3) -> list[Job]:
        jobs = []
        for name in self.sources:
            scraper = self.scrapers.get(name)
            if scraper:
                print(f"  Scraping {name.capitalize()}...")
                jobs.extend(scraper.scrape(self.keywords, self.location,
                                           pages, self.HEADERS))

        jobs = self._dedup(jobs)
        jobs = self._filter_excluded(jobs)
        for job in jobs:
            self._score_job(job)
        jobs.sort(key=lambda j: j.match_score, reverse=True)
        return jobs

    def _dedup(self, jobs: list[Job]) -> list[Job]:
        seen = set()
        unique = []
        for j in jobs:
            key = (j.title.lower().strip(), j.company.lower().strip())
            if key not in seen:
                seen.add(key)
                unique.append(j)
        return unique

    def _filter_excluded(self, jobs: list[Job]) -> list[Job]:
        exclude = [k.lower() for k in self.profile.get("exclude_keywords", [])]
        if not exclude:
            return jobs
        return [j for j in jobs if not any(k in j.title.lower() for k in exclude)]

    def _score_job(self, job: Job):
        text = f"{job.title} {job.summary}".lower()
        score = 0.0
        matched, missing = [], []

        for kw in self.profile.get("title_keywords", []):
            if kw.lower() in job.title.lower():
                score += 30 / max(len(self.profile["title_keywords"]), 1)

        for skill in self.profile.get("must_have_skills", []):
            if re.search(rf'\b{re.escape(skill)}\b', text, re.IGNORECASE):
                score += 40 / max(len(self.profile["must_have_skills"]), 1)
                matched.append(skill)
            else:
                missing.append(skill)

        for skill in self.profile.get("nice_to_have_skills", []):
            if re.search(rf'\b{re.escape(skill)}\b', text, re.IGNORECASE):
                score += 20 / max(len(self.profile["nice_to_have_skills"]), 1)
                matched.append(skill)

        locs = self.profile.get("preferred_locations", [])
        if not locs or any(l.lower() in job.location.lower() for l in locs):
            score += 10

        exp_match = re.search(r'(\d+)\+?\s*(?:years|yrs)', text)
        if exp_match and int(exp_match.group(1)) > self.profile.get("max_experience_years", 99):
            score -= 20

        job.match_score = round(min(score, 100), 1)
        job.matched_skills = matched
        job.missing_skills = missing


def main():
    parser = argparse.ArgumentParser(description="Job Search Agent")
    parser.add_argument("keywords", help="Search keywords")
    parser.add_argument("-l", "--location", default="")
    parser.add_argument("-p", "--pages", type=int, default=3)
    parser.add_argument("--profile", default="profile.json")
    parser.add_argument("--sources", nargs="*", default=["indeed", "linkedin"],
                        choices=["indeed", "linkedin"])
    parser.add_argument("--min-score", type=float, default=0)
    parser.add_argument("-o", "--output", help="Save to JSON")
    args = parser.parse_args()

    with open(args.profile) as f:
        profile = json.load(f)

    agent = JobSearchAgent(args.keywords, args.location, profile, args.sources)
    print(f"Searching for '{args.keywords}' in '{args.location or 'anywhere'}'...")
    jobs = agent.search(args.pages)

    if args.min_score:
        jobs = [j for j in jobs if j.match_score >= args.min_score]

    print(f"\nFound {len(jobs)} matching jobs (sorted by relevance):\n")
    for i, job in enumerate(jobs, 1):
        bar = "█" * int(job.match_score / 5) + "░" * (20 - int(job.match_score / 5))
        src = f"[{job.source}]"
        print(f"  {i}. [{job.match_score:5.1f}%] {bar} {src:10s} {job.title}")
        print(f"     {job.company} | {job.location}")
        if job.salary:
            print(f"     💰 {job.salary}")
        if job.matched_skills:
            print(f"     ✅ Matched: {', '.join(job.matched_skills)}")
        if job.missing_skills:
            print(f"     ❌ Missing: {', '.join(job.missing_skills)}")
        if job.url:
            print(f"     🔗 {job.url}")
        print()

    if args.output:
        with open(args.output, "w") as f:
            json.dump([vars(j) for j in jobs], f, indent=2)
        print(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
