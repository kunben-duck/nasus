package com.autotest.platform.repository;

import com.autotest.platform.entity.TestScript;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface TestScriptRepository extends JpaRepository<TestScript, Long> {

    Optional<TestScript> findByIdAndTenantId(Long id, Long tenantId);

    Optional<TestScript> findByTestCaseId(Long testCaseId);

    Optional<TestScript> findByTestCaseIdAndTenantId(Long testCaseId, Long tenantId);

    Page<TestScript> findByTenantId(Long tenantId, Pageable pageable);

    @Query("SELECT ts FROM TestScript ts WHERE ts.tenantId = :tenantId AND ts.status = :status")
    List<TestScript> findByStatus(@Param("tenantId") Long tenantId,
                                  @Param("status") TestScript.Status status);

    @Query("SELECT ts FROM TestScript ts WHERE ts.tenantId = :tenantId AND ts.scriptType = :type")
    Page<TestScript> findByScriptType(@Param("tenantId") Long tenantId,
                                      @Param("type") TestScript.ScriptType type,
                                      Pageable pageable);

    @Query("SELECT ts FROM TestScript ts WHERE ts.tenantId = :tenantId AND ts.language = :language")
    Page<TestScript> findByLanguage(@Param("tenantId") Long tenantId,
                                    @Param("language") TestScript.Language language,
                                    Pageable pageable);

    @Query("SELECT COUNT(ts) FROM TestScript ts WHERE ts.tenantId = :tenantId AND ts.status = :status")
    long countByStatus(@Param("tenantId") Long tenantId,
                       @Param("status") TestScript.Status status);

    @Query("SELECT COUNT(ts) FROM TestScript ts WHERE ts.tenantId = :tenantId AND ts.scriptType = :type")
    long countByScriptType(@Param("tenantId") Long tenantId,
                           @Param("type") TestScript.ScriptType type);

    long countByTenantId(Long tenantId);
}
