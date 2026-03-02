package com.autotest.platform.repository;

import com.autotest.platform.entity.TestExecution;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface TestExecutionRepository extends JpaRepository<TestExecution, Long> {

    Optional<TestExecution> findByExecutionId(String executionId);

    Optional<TestExecution> findByExecutionIdAndTenantId(String executionId, Long tenantId);

    Optional<TestExecution> findByIdAndTenantId(Long id, Long tenantId);

    Page<TestExecution> findByTenantId(Long tenantId, Pageable pageable);

    @Query("SELECT te FROM TestExecution te WHERE te.tenantId = :tenantId AND te.testCase.id = :testCaseId ORDER BY te.createdAt DESC")
    List<TestExecution> findByTestCaseId(@Param("tenantId") Long tenantId,
                                         @Param("testCaseId") Long testCaseId);

    @Query("SELECT te FROM TestExecution te WHERE te.tenantId = :tenantId AND te.status = :status")
    Page<TestExecution> findByStatus(@Param("tenantId") Long tenantId,
                                     @Param("status") TestExecution.ExecutionStatus status,
                                     Pageable pageable);

    @Query("SELECT te FROM TestExecution te WHERE te.tenantId = :tenantId AND te.result = :result")
    Page<TestExecution> findByResult(@Param("tenantId") Long tenantId,
                                     @Param("result") TestExecution.ExecutionResult result,
                                     Pageable pageable);

    @Query("SELECT te FROM TestExecution te WHERE te.tenantId = :tenantId AND te.executedBy = :username")
    Page<TestExecution> findByExecutedBy(@Param("tenantId") Long tenantId,
                                         @Param("username") String username,
                                         Pageable pageable);

    @Query("SELECT te FROM TestExecution te WHERE te.tenantId = :tenantId AND te.createdAt BETWEEN :start AND :end")
    List<TestExecution> findByTimeRange(@Param("tenantId") Long tenantId,
                                        @Param("start") LocalDateTime start,
                                        @Param("end") LocalDateTime end);

    @Query("SELECT COUNT(te) FROM TestExecution te WHERE te.tenantId = :tenantId AND te.status = :status")
    long countByStatus(@Param("tenantId") Long tenantId,
                       @Param("status") TestExecution.ExecutionStatus status);

    @Query("SELECT COUNT(te) FROM TestExecution te WHERE te.tenantId = :tenantId AND te.result = :result")
    long countByResult(@Param("tenantId") Long tenantId,
                       @Param("result") TestExecution.ExecutionResult result);

    @Query("SELECT COUNT(te) FROM TestExecution te WHERE te.tenantId = :tenantId AND te.createdAt >= :since")
    long countSince(@Param("tenantId") Long tenantId,
                    @Param("since") LocalDateTime since);

    @Query("SELECT AVG(te.duration) FROM TestExecution te WHERE te.tenantId = :tenantId AND te.duration IS NOT NULL")
    Double getAverageDuration(@Param("tenantId") Long tenantId);

    @Query("SELECT te FROM TestExecution te WHERE te.tenantId = :tenantId ORDER BY te.createdAt DESC")
    List<TestExecution> findRecentExecutions(@Param("tenantId") Long tenantId,
                                             Pageable pageable);

    long countByTenantId(Long tenantId);
}
