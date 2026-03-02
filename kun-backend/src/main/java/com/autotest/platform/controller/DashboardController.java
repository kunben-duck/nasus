package com.autotest.platform.controller;

import com.autotest.platform.dto.ApiResponse;
import com.autotest.platform.dto.DashboardDTO;
import com.autotest.platform.service.DashboardService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/dashboard")
@RequiredArgsConstructor
@Slf4j
@CrossOrigin(origins = "*")
public class DashboardController {
    
    private final DashboardService dashboardService;
    
    @GetMapping
    public ResponseEntity<ApiResponse<DashboardDTO>> getDashboard(
            @RequestParam(name = "trendDays", required = false) Integer trendDays) {
        log.debug("Fetching dashboard data");
        DashboardDTO dashboard = dashboardService.getDashboardData(trendDays);
        return ResponseEntity.ok(ApiResponse.success(dashboard));
    }
    
    @GetMapping("/statistics")
    public ResponseEntity<ApiResponse<DashboardDTO.Statistics>> getStatistics() {
        log.debug("Fetching statistics");
        DashboardDTO dashboard = dashboardService.getDashboardData();
        return ResponseEntity.ok(ApiResponse.success(dashboard.getStatistics()));
    }
    
    @GetMapping("/charts")
    public ResponseEntity<ApiResponse<DashboardDTO.Charts>> getCharts(
            @RequestParam(name = "trendDays", required = false) Integer trendDays) {
        log.debug("Fetching charts");
        DashboardDTO dashboard = dashboardService.getDashboardData(trendDays);
        return ResponseEntity.ok(ApiResponse.success(dashboard.getCharts()));
    }
    
    @GetMapping("/recent-activities")
    public ResponseEntity<ApiResponse<DashboardDTO.RecentActivities>> getRecentActivities() {
        log.debug("Fetching recent activities");
        DashboardDTO dashboard = dashboardService.getDashboardData();
        return ResponseEntity.ok(ApiResponse.success(dashboard.getRecentActivities()));
    }
    
    @GetMapping("/system-status")
    public ResponseEntity<ApiResponse<DashboardDTO.SystemStatus>> getSystemStatus() {
        log.debug("Fetching system status");
        DashboardDTO dashboard = dashboardService.getDashboardData();
        return ResponseEntity.ok(ApiResponse.success(dashboard.getSystemStatus()));
    }
}
