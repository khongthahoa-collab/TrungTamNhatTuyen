ROLE & CONTEXT

You are an expert Senior Enterprise System Architect, Lead DevOps Engineer, and Principal Web Security Architect.
Our goal is to compile a comprehensive, professional-grade, and cohesive "System Architecture, Security & Deployment Blueprint" (Tài liệu Đặc tả & Hướng dẫn Vận hành Hệ thống) based on the architectural decisions and optimizations discussed.

The application is built on:

Backend: Python (Flask Framework) with SQLAlchemy ORM and Flask-Migrate.

Database: Supabase (Enterprise-grade PostgreSQL).

DNS, WAF & Routing: Cloudflare (Proxied, Cloudflare Tunnel, Zero Trust).

Hosting: Railway (Separate services for Isolation).

ARCHITECTURAL DECISIONS TO INCORPORATE

MULTI-ENVIRONMENT SEGREGATION:

Production (ABC.com): Listening to Git main branch, running on Railway Service school-portal-prod. Connecting to Supabase Production (Pro Tier + IPv4 Add-on).

Staging (test-ABC.com): Listening to Git dev branch, running on Railway Service school-portal-staging. Connecting to Supabase Staging (Free Tier).

Security Hardening for Staging: Gated behind Cloudflare Access / Zero Trust (only allowing Google Auth for internal staff emails e.g., @trungtam.com), disabling raw debug traceback in Flask to prevent variable leakage.

DATABASE CONNECTIVITY & BYPASSES:

Supabase Free Tier direct connection on port 5432 is restricted to IPv6 by default.

For Flask (Stateful/Persistent connections), the system MUST connect via the Session Pooler (port 5432 of the host *.pooler.supabase.com) to support dual-stack (IPv4 & IPv6 compatibility) natively on Free Tier.

Database Hardening: Mandating SSL (sslmode=require), Cloud Firewall/Network Restrictions to only allow connection from the Flask host IP, and utilizing the Least Privilege User Account model (separate app_user with restricted DML privileges instead of superuser postgres).

HIGH-PERFORMANCE ONLINE EXAM SUBDOMAIN (exam.ABC.com):

Service Isolation: Run as a separate Railway service school-portal-exam connected to the database transaction pooler (port 6543) of Supabase to handle massive concurrency without exhausting direct Postgres connections.

Client-side Auto-Save (Debounce Sync): Debouncing response uploads to local storage and syncing with the server every 30 seconds to prevent request storms.

Exam Content Caching: Caching static exams in Redis or memory (Flask-Caching) so subsequent reads hit the cache under 2ms, bypassing the database.

Anti-Cheat Hardening: Locking right-clicks, text selection, copy-paste shortcuts (Ctrl+C, Ctrl+V, F12). Using the Javascript Page Visibility API (visibilitychange) to trigger Fullscreen warning on focus loss, and forcing auto-submit on the 3rd infraction.

DEPLOYMENT & ZERO-PORT EXPOSURE (CLOUDFLARE TUNNEL):

Deploying using Docker Containerization on a VPS (Hetzner, DigitalOcean, or AWS EC2).

Securing the VPS using a Cloudflare Tunnel (cloudflared daemon).

VPS CLOSES ALL INBOUND PORTS (No open ports 80, 443, or 22). All web traffic is securely proxied over an encrypted tunnel established outwards from the VPS to Cloudflare edge networks.

TASKS FOR CLAUDE.AI

Please generate a single, unified, master documentation handbook in Markdown format. The document must be written in Vietnamese with technical security terms kept in English. It must include:

PHẦN 1: TỔNG QUAN KIẾN TRÚC & PHÂN TÁCH ĐA MÔI TRƯỜNG

Detailed technical diagram (ASCII Art) of the multi-environment separation (Prod, Staging, Exam Subdomain).

Deep explanation of the isolation principle and why we separate Staging and Prod.

Gating mechanism of Cloudflare Zero Trust on test-ABC.com.

PHẦN 2: THIẾT KẾ CƠ SỞ DỮ LIỆU & GIẢI PHÁP MẠNG

How to resolve Supabase Free IPv6 restriction using the Session Pooler (port 5432).

Comparison matrix of database hosting strategies (Supabase Pro vs Managed RDS vs Self-Hosted).

Hardening specifications: SSL requirement, Network Restrictions (IP Allowlisting), and Least Privilege Principle.

A production-ready shell script for daily automated logical backups.

PHẦN 3: KIẾN TRÚC THI ONLINE HIỆU NĂNG CAO (exam.ABC.com)

Explaining the Transaction Pooler (port 6543) mechanics under high concurrency.

Client-side debounce auto-save algorithm.

Server-side exam caching architecture.

Frontend Javascript code snippets for Page Visibility API anti-cheat and lock keys.

PHẦN 4: CẨM NĂNG TRIỂN KHAI & DI TRÚ (PRODUCTION RUNBOOK)

Complete, non-mock Dockerfile and docker-compose.yml configured to bind ONLY to 127.0.0.1 (safeguarding localhost).

Step-by-step instructions to configure Cloudflare Tunnel on Ubuntu Server.

Step-by-step instructions for custom domain CNAME records routing on Cloudflare.

Standard Git Flow strategy (Code Promotion from dev to main) and local migration setups using Flask-Migrate (Alembic).

Ensure there are absolutely no placeholder variables or unwritten code blocks (like // TODO or ...). Everything must be completely written out, robust, secure, and ready for deployment.