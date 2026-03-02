package com.autotest.platform.repository;

import com.autotest.platform.entity.TestCase;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface TestCaseRepository extends JpaRepository<TestCase, Long> {

    Optional<TestCase> findByCaseNumber(String caseNumber);

    Optional<TestCase> findByCaseNumberAndTenantId(String caseNumber, Long tenantId);

    Optional<TestCase> findByIdAndTenantId(Long id, Long tenantId);

    boolean existsByCaseNumber(String caseNumber);

    boolean existsByCaseNumberAndTenantId(String caseNumber, Long tenantId);

    Page<TestCase> findByTenantId(Long tenantId, Pageable pageable);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.userStory.id = :usId")
    List<TestCase> findByUserStoryId(@Param("tenantId") Long tenantId,
                                     @Param("usId") Long usId);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.status = :status")
    Page<TestCase> findByStatus(@Param("tenantId") Long tenantId,
                                @Param("status") TestCase.Status status,
                                Pageable pageable);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.testType = :type")
    Page<TestCase> findByTestType(@Param("tenantId") Long tenantId,
                                  @Param("type") TestCase.TestType type,
                                  Pageable pageable);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.priority = :priority")
    Page<TestCase> findByPriority(@Param("tenantId") Long tenantId,
                                  @Param("priority") TestCase.Priority priority,
                                  Pageable pageable);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.createdBy.id = :userId")
    Page<TestCase> findByCreatedBy(@Param("tenantId") Long tenantId,
                                   @Param("userId") Long userId,
                                   Pageable pageable);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND (" +
            "tc.caseNumber LIKE %:keyword% OR " +
            "tc.title LIKE %:keyword% OR " +
            "tc.description LIKE %:keyword% OR " +
            "tc.tags LIKE %:keyword%)")
    Page<TestCase> searchTestCases(@Param("tenantId") Long tenantId,
                                   @Param("keyword") String keyword,
                                   Pageable pageable);

    @Query("SELECT tc FROM TestCase tc WHERE tc.tenantId = :tenantId AND " +
            "(:keyword IS NULL OR :keyword = '' OR " +
            "LOWER(tc.caseNumber) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(tc.title) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(COALESCE(tc.description, '')) LIKE LOWER(CONCAT('%', :keyword, '%')) OR " +
            "LOWER(COALESCE(tc.tags, '')) LIKE LOWER(CONCAT('%', :keyword, '%'))) " +
            "AND (:status IS NULL OR tc.status = :status) " +
            "AND (:type IS NULL OR tc.testType = :type) " +
            "AND (:priority IS NULL OR tc.priority = :priority)")
    Page<TestCase> findByFilters(@Param("tenantId") Long tenantId,
                                 @Param("keyword") String keyword,
                                 @Param("status") TestCase.Status status,
                                 @Param("type") TestCase.TestType type,
                                 @Param("priority") TestCase.Priority priority,
                                 Pageable pageable);

    @Query("SELECT COUNT(tc) FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.status = :status")
    long countByStatus(@Param("tenantId") Long tenantId,
                       @Param("status") TestCase.Status status);

    @Query("SELECT COUNT(tc) FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.testType = :type")
    long countByTestType(@Param("tenantId") Long tenantId,
                         @Param("type") TestCase.TestType type);

    @Query("SELECT COUNT(tc) FROM TestCase tc WHERE tc.tenantId = :tenantId AND tc.userStory.id = :usId")
    long countByUserStoryId(@Param("tenantId") Long tenantId,
                            @Param("usId") Long usId);

    long countByTenantId(Long tenantId);
}
