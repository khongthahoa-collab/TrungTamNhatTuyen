#!/bin/bash

# 🚀 DEPLOYMENT HELPER SCRIPT
# Usage: ./deploy.sh [railway|docker|heroku]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}════════════════════════════════════════${NC}"
echo -e "${YELLOW}  NHẠt TUYẾN - DEPLOYMENT HELPER${NC}"
echo -e "${YELLOW}════════════════════════════════════════${NC}\n"

# Check if git is clean
if [[ -n $(git status -s) ]]; then
    echo -e "${RED}❌ Git working directory is dirty. Please commit all changes:${NC}"
    git status -s
    exit 1
fi

# Function: Deploy to Railway
deploy_railway() {
    echo -e "${YELLOW}📦 Preparing for Railway deployment...${NC}\n"
    
    # Check Railway CLI
    if ! command -v railway &> /dev/null; then
        echo -e "${RED}❌ Railway CLI not found. Install it:${NC}"
        echo "   npm install -g @railway/cli"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Railway CLI found${NC}"
    
    # Login to Railway
    echo -e "\n${YELLOW}🔑 Login to Railway...${NC}"
    railway login
    
    # Create or link project
    echo -e "\n${YELLOW}📱 Linking project...${NC}"
    railway link || railway init
    
    # Deploy
    echo -e "\n${YELLOW}🚀 Deploying to Railway...${NC}"
    railway up --service api
    
    echo -e "\n${GREEN}✅ Deployment to Railway completed!${NC}"
    echo -e "${YELLOW}Visit your Railway dashboard:${NC} https://railway.app/dashboard"
}

# Function: Deploy to Docker
deploy_docker() {
    echo -e "${YELLOW}🐳 Preparing Docker deployment...${NC}\n"
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker not found. Install it from https://docker.com${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Docker found${NC}\n"
    
    # Create .env.prod
    if [ ! -f .env.prod ]; then
        echo -e "${YELLOW}📝 Creating .env.prod...${NC}"
        cat > .env.prod << EOF
FLASK_ENV=production
SECRET_KEY=$(openssl rand -hex 32)
DB_USER=nhat_tuyen_user
DB_PASSWORD=$(openssl rand -hex 16)
DB_ROOT_PASSWORD=$(openssl rand -hex 16)
DB_NAME=nhat_tuyen_db
EOF
        echo -e "${GREEN}✓ .env.prod created${NC}"
    else
        echo -e "${YELLOW}⚠️  .env.prod already exists, skipping...${NC}"
    fi
    
    # Build and run
    echo -e "\n${YELLOW}🔨 Building Docker images...${NC}"
    docker-compose -f docker-compose.prod.yml build
    
    echo -e "\n${YELLOW}🚀 Starting containers...${NC}"
    docker-compose -f docker-compose.prod.yml up -d
    
    # Wait for DB to be ready
    echo -e "\n${YELLOW}⏳ Waiting for database to be ready...${NC}"
    sleep 10
    
    # Initialize database
    echo -e "\n${YELLOW}🗄️  Initializing database...${NC}"
    docker-compose -f docker-compose.prod.yml exec -T web python -c \
        "from app import create_app, db; app=create_app('production'); db.create_all()"
    
    # Show status
    echo -e "\n${GREEN}✅ Docker deployment completed!${NC}"
    echo -e "\n${YELLOW}📊 Container status:${NC}"
    docker-compose -f docker-compose.prod.yml ps
    
    echo -e "\n${YELLOW}📍 App should be running at:${NC}"
    echo "   http://localhost:80"
    
    echo -e "\n${YELLOW}📋 Useful commands:${NC}"
    echo "   View logs: docker-compose -f docker-compose.prod.yml logs -f web"
    echo "   Stop: docker-compose -f docker-compose.prod.yml down"
    echo "   Restart: docker-compose -f docker-compose.prod.yml restart"
}

# Function: Deploy to Heroku
deploy_heroku() {
    echo -e "${YELLOW}🦅 Preparing Heroku deployment...${NC}\n"
    
    # Check Heroku CLI
    if ! command -v heroku &> /dev/null; then
        echo -e "${RED}❌ Heroku CLI not found. Install it:${NC}"
        echo "   brew tap heroku/brew && brew install heroku"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Heroku CLI found${NC}\n"
    
    # Login
    echo -e "${YELLOW}🔑 Login to Heroku...${NC}"
    heroku login
    
    # Create app if not exists
    echo -e "\n${YELLOW}📱 Creating/linking Heroku app...${NC}"
    APP_NAME="${1:-nhat-tuyen-app}"
    
    if heroku apps:info -a "$APP_NAME" &> /dev/null; then
        echo -e "${GREEN}✓ App '$APP_NAME' found${NC}"
    else
        echo -e "${YELLOW}Creating new Heroku app: $APP_NAME${NC}"
        heroku create "$APP_NAME"
    fi
    
    # Add MySQL
    echo -e "\n${YELLOW}🗄️  Adding ClearDB MySQL add-on...${NC}"
    heroku addons:create cleardb:ignite --app "$APP_NAME" || \
        echo -e "${YELLOW}⚠️  Add-on already exists or not available${NC}"
    
    # Set config vars
    echo -e "\n${YELLOW}⚙️  Setting configuration...${NC}"
    heroku config:set FLASK_ENV=production --app "$APP_NAME"
    heroku config:set SECRET_KEY=$(openssl rand -hex 32) --app "$APP_NAME"
    
    # Deploy
    echo -e "\n${YELLOW}🚀 Deploying to Heroku...${NC}"
    git push heroku main
    
    # Initialize database
    echo -e "\n${YELLOW}🗄️  Initializing database...${NC}"
    heroku run "python -c 'from app import create_app, db; app=create_app(\"production\"); db.create_all()'" --app "$APP_NAME"
    
    # Open app
    echo -e "\n${GREEN}✅ Deployment to Heroku completed!${NC}"
    echo -e "${YELLOW}Opening app in browser...${NC}"
    heroku open --app "$APP_NAME"
}

# Function: Show help
show_help() {
    echo -e "${YELLOW}Usage:${NC}"
    echo "  ./deploy.sh [platform] [options]"
    echo ""
    echo -e "${YELLOW}Platforms:${NC}"
    echo "  railway    - Deploy to Railway (Recommended for test)"
    echo "  docker     - Deploy using Docker + Docker Compose"
    echo "  heroku     - Deploy to Heroku"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  ./deploy.sh railway"
    echo "  ./deploy.sh docker"
    echo "  ./deploy.sh heroku"
    echo ""
}

# Main logic
case "${1:-help}" in
    railway)
        deploy_railway
        ;;
    docker)
        deploy_docker
        ;;
    heroku)
        deploy_heroku "${2:-nhat-tuyen-app}"
        ;;
    *)
        show_help
        ;;
esac
