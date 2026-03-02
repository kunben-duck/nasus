#!/bin/bash

# AutoTest Platform - Spring Boot Startup Script

set -e

APP_NAME="AutoTest Platform"
APP_PORT=8080

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check Java version
check_java() {
    if ! command -v java &> /dev/null; then
        log_error "Java is not installed. Please install JDK 17 or higher."
        exit 1
    fi
    
    JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}')
    log_info "Java version: $JAVA_VERSION"
}

# Download Maven if not exists
download_maven() {
    if [ ! -d "$HOME/.m2/wrapper/apache-maven-3.9.6" ]; then
        log_info "Downloading Maven..."
        mkdir -p "$HOME/.m2/wrapper"
        cd "$HOME/.m2/wrapper"
        
        if command -v wget &> /dev/null; then
            wget -q https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz
        elif command -v curl &> /dev/null; then
            curl -sL -o apache-maven-3.9.6-bin.tar.gz https://archive.apache.org/dist/maven/maven-3/3.9.6/binaries/apache-maven-3.9.6-bin.tar.gz
        else
            log_error "Neither wget nor curl is available. Please install one of them."
            exit 1
        fi
        
        tar -xzf apache-maven-3.9.6-bin.tar.gz
        rm apache-maven-3.9.6-bin.tar.gz
        log_success "Maven downloaded successfully"
    fi
    
    export PATH="$HOME/.m2/wrapper/apache-maven-3.9.6/bin:$PATH"
}

# Build the project
build_project() {
    log_info "Building $APP_NAME..."
    cd "$(dirname "$0")"
    
    # Download dependencies and build
    mvn clean package -DskipTests -q
    
    log_success "Build completed successfully"
}

# Run the application
run_application() {
    log_info "Starting $APP_NAME..."
    
    # Find the JAR file
    JAR_FILE=$(find target -name "*.jar" -not -name "*sources*" -not -name "*javadoc*" | head -1)
    
    if [ -z "$JAR_FILE" ]; then
        log_error "JAR file not found. Please build the project first."
        exit 1
    fi
    
    log_info "JAR file: $JAR_FILE"
    log_info "Application will be available at: http://localhost:$APP_PORT/api"
    log_info "H2 Console: http://localhost:$APP_PORT/api/h2-console"
    log_info "Health Check: http://localhost:$APP_PORT/api/actuator/health"
    log_info "Press Ctrl+C to stop the application"
    echo ""
    
    # Run the application
    java -jar "$JAR_FILE"
}

# Main function
main() {
    echo "========================================"
    echo "  $APP_NAME - Spring Boot"
    echo "========================================"
    echo ""
    
    check_java
    download_maven
    build_project
    run_application
}

# Handle Ctrl+C
trap 'log_warning "Shutting down..."; exit 0' INT

main "$@"
