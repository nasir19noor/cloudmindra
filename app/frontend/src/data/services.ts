export interface Service {
  slug: string;
  title: string;
  headline: string;
  summary: string;
  description: string;
  features: string[];
}

export const services: Service[] = [
  {
    slug: 'cloud',
    title: 'Cloud Infrastructure',
    headline: 'Build on solid ground',
    summary: 'AWS, GCP, and Azure architecture designed for scale and cost.',
    description:
      'Design, build, and manage cloud environments on AWS, GCP, and Azure. We architect solutions that are scalable, cost-effective, and production-ready.',
    features: ['Multi-cloud architecture', 'Cloud migration', 'Cost optimization', 'High availability design'],
  },
  {
    slug: 'ai',
    title: 'AI & Machine Learning',
    headline: 'Put AI to real work',
    summary: 'LLM integration, custom models, and AI that ships to production.',
    description:
      'Custom AI solutions from concept to production. We integrate LLMs, build predictive models, and deploy intelligent automation into your workflows.',
    features: ['LLM integration', 'Custom model training', 'AI-powered automation', 'Predictive analytics'],
  },
  {
    slug: 'devops',
    title: 'DevOps & Automation',
    headline: 'Ship faster, safely',
    summary: 'CI/CD, Infrastructure as Code, and container orchestration.',
    description:
      'End-to-end CI/CD pipelines, Infrastructure as Code, container orchestration, and observability. We automate your entire development lifecycle.',
    features: ['CI/CD pipelines', 'Terraform / IaC', 'Kubernetes', 'Monitoring & alerting'],
  },
  {
    slug: 'data',
    title: 'Data Engineering',
    headline: 'Turn data into decisions',
    summary: 'Pipelines, analytics platforms, and data lake architecture.',
    description:
      'Build data pipelines, analytics platforms, and data lakes. We help you collect, process, and derive actionable insights from your data.',
    features: ['ETL pipelines', 'Data lake architecture', 'Real-time analytics', 'Data governance'],
  },
  {
    slug: 'security',
    title: 'Cloud Security',
    headline: 'Secure every layer',
    summary: 'IAM strategy, compliance frameworks, and vulnerability assessment.',
    description:
      'Comprehensive security strategy including IAM, compliance frameworks, vulnerability assessment, and security automation.',
    features: ['IAM & access control', 'Compliance (SOC2, ISO)', 'Vulnerability scanning', 'Incident response'],
  },
  {
    slug: 'consulting',
    title: 'Consulting',
    headline: 'Plan the right path',
    summary: 'Cloud strategy, cost reviews, and architecture guidance.',
    description:
      'Strategic guidance for your cloud journey. From initial assessment to technology roadmap, we help you make informed decisions.',
    features: ['Architecture review', 'Cloud strategy', 'Cost analysis', 'Technology roadmap'],
  },
];
